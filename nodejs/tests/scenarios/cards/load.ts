import { createHash } from 'crypto'
import { existsSync, readFileSync } from 'fs'
import path from 'path'
import { parse, stringify } from 'yaml'
import { z } from 'zod'

import { parseNumberFromEnv } from '~/common/config'
import { getDefaultConfig } from '~/common/config/config'

import { TRAFFIC } from '../generator/traffic'
import { DEFINITIONS, Definition, Definitions } from './definitions'
import { Card, Named, Profile, stepsOf } from './schema'
import { Target, targetProblems } from './target'

export const PROFILES_DIR = path.join(__dirname, '..', 'profiles')
export const ROLE_RESTART_BACKOFF_MS = 2000
const PROCESS_ENV_SETTINGS = ['HOG_BYTECODE_CACHE_REQUIRED', 'HOG_BYTECODE_CACHE_REWRITE']
export const LOAD_PRODUCER_SETTING_PREFIX = 'KAFKA_PRODUCER_'

export type LoadedCard = { card: Card; profile: Profile; cardHash: string; profileHash: string }

export type LoadOptions = { profilePath?: string; target?: Target }

export class CardError extends Error {
    constructor(
        readonly file: string,
        readonly problems: string[]
    ) {
        super(`${file} is not a valid card:\n${problems.map((problem) => `- ${problem}`).join('\n')}`)
        this.name = 'CardError'
    }
}

function problemsOf(error: z.ZodError, prefix: string): string[] {
    return error.issues.map(
        (issue) => `${[prefix, ...issue.path].filter((part) => part !== '').join('.')}: ${issue.message}`
    )
}

type Read = { value: unknown } | { problem: string }

function parseYaml(text: () => string, label: string): Read {
    try {
        return { value: parse(text(), { maxAliasCount: 0 }) }
    } catch (error) {
        return { problem: `${label}: ${(error as Error).message}` }
    }
}

function readYaml(file: string, label: string): Read {
    if (!existsSync(file)) {
        return { problem: `${label}: no file at ${file}` }
    }
    return parseYaml(() => readFileSync(file, 'utf8'), label)
}

function sha256(value: unknown): string {
    return createHash('sha256')
        .update(stringify(value, { sortMapEntries: true }))
        .digest('hex')
}

function checkNamed(kind: string, where: string, entry: Named, definitions: Definition[]): string[] {
    const definition = definitions.find(({ name }) => name === entry.name)
    if (!definition) {
        return [`${where}.name: unknown ${kind} ${entry.name}`]
    }
    const params = definition.params.safeParse(entry.params)
    return params.success ? [] : problemsOf(params.error, `${where}.params`)
}

function checkNames(card: Card, definitions: Definitions): string[] {
    return [
        ...card.drive.traffic.flatMap((entry, i) =>
            checkNamed('traffic kind', `drive.traffic.${i}`, entry, definitions.traffic)
        ),
        ...card.invariants.flatMap((entry, i) =>
            checkNamed('invariant', `invariants.${i}`, entry, definitions.invariants)
        ),
        ...card.measure.flatMap((entry, i) =>
            checkNamed('measurement', `measure.${i}`, entry, definitions.measurements)
        ),
        ...card.bars.flatMap((entry, i) => checkNamed('bar', `bars.${i}`, entry, definitions.bars)),
        ...card.valves.flatMap((entry, i) => {
            const definition = definitions.valves.find(({ name }) => name === entry.valve)
            if (!definition) {
                return [`valves.${i}.valve: unknown valve ${entry.valve}`]
            }
            const target = definition.target.safeParse(entry.target)
            const dose = definition.params.safeParse(entry.dose)
            return [
                ...(target.success ? [] : problemsOf(target.error, `valves.${i}.target`)),
                ...(dose.success ? [] : problemsOf(dose.error, `valves.${i}.dose`)),
            ]
        }),
    ]
}

type Settings = Record<string, unknown>

function checkSuppression(card: Card): string[] {
    const bounces = card.valves.some(({ valve, dose }) => valve === 'ses.reject' && dose.type === 'bounce')
    return card.invariants.flatMap(({ name }, i) =>
        name === 'bounced_suppressed' && !bounces
            ? [`invariants.${i}.name: bounced_suppressed needs a ses.reject entry with type bounce`]
            : []
    )
}

const ANSWERED_AT_INTAKE = TRAFFIC.filter(({ intake }) => intake !== 'event').map(({ name }) => name)

function checkIntakeVerdict(card: Card): string[] {
    const unjudged = card.drive.traffic.filter(({ name }) => ANSWERED_AT_INTAKE.includes(name))
    if (unjudged.length === 0 || card.invariants.some(({ name }) => name === 'refused_at_intake')) {
        return []
    }
    return [
        `invariants: ${unjudged.map(({ name }) => name).join(', ')} counts a unit its intake refused as offered, so the card needs refused_at_intake`,
    ]
}

function checkProfile(card: Card, profile: Profile, definitions: Definitions, defaults: Record<string, unknown>) {
    const rolesRead = (name: string): boolean => Object.hasOwn(defaults, name) || PROCESS_ENV_SETTINGS.includes(name)
    const loadProducerReads = (name: string): boolean => name.startsWith(LOAD_PRODUCER_SETTING_PREFIX)
    return [
        ...Object.keys(profile.settings)
            .filter((name) => !rolesRead(name) && !loadProducerReads(name))
            .map((name) => `profile.settings.${name}: not a setting the roles or the load producer read`),
        ...card.drive.traffic.flatMap(({ name }) => {
            const definition = definitions.traffic.find((traffic) => traffic.name === name)
            const traffic = definition?.profile.safeParse(profile.traffic[name])
            return traffic === undefined || traffic.success ? [] : problemsOf(traffic.error, `profile.traffic.${name}`)
        }),
    ]
}

// The event pipeline rate limits each workflow, and each seeded team runs one workflow per traffic kind, so a kind's
// load splits over setup.teams workflows. A card that brings any of them near the limit would measure the limit, not
// the queue.
const RATE_LIMIT_SHARE = 0.8

// The card may load on a machine other than the run host, so only the profile can set the limit its roles run with.
function checkWorkflowRate(card: Card, profile: Profile, defaults: Settings): string[] {
    const key = 'CDP_RATE_LIMITER_REFILL_RATE'
    const fallback = Number(defaults[key])
    const raw = profile.settings[key]
    const limit = raw === undefined ? fallback : parseNumberFromEnv(key, String(raw), fallback)
    const ceiling = limit * RATE_LIMIT_SHARE
    const topScale = Math.max(...stepsOf(card.drive).map(({ scale }) => scale))
    return card.drive.traffic.flatMap(({ name }) => {
        const kind = TRAFFIC.find((traffic) => traffic.name === name)
        const shape = kind?.profile.safeParse(profile.traffic[name])
        if (kind === undefined || kind.intake === 'transactional' || !shape?.success) {
            return []
        }
        const perWorkflow = (shape.data.ratePerSecond * topScale) / card.setup.teams
        return perWorkflow <= ceiling
            ? []
            : [
                  `setup.teams: ${name} sends ${perWorkflow} units a second to each team's workflow at the ${topScale}x step, over ${ceiling}, ${RATE_LIMIT_SHARE * 100}% of the per-workflow rate limit; spread it over ${Math.ceil((perWorkflow * card.setup.teams) / ceiling)} teams or more`,
              ]
    })
}

// Each listing seeds its own workflow per team, and both match the kind's events, so every unit would run twice.
function checkTrafficOnce(card: Card): string[] {
    const listed = card.drive.traffic.map(({ name }) => name)
    return [...new Set(listed)]
        .filter((name) => TRAFFIC.find((traffic) => traffic.name === name)?.intake === 'event')
        .map((name) => ({ name, times: listed.filter((listedName) => listedName === name).length }))
        .filter(({ times }) => times > 1)
        .map(({ name, times }) => `drive.traffic: ${name} is listed ${times} times; list each traffic kind once`)
}

type ProfileRead = { profile: Profile } | { problems: string[] }

function loadProfile(card: Card, profilePath: string | undefined): ProfileRead {
    const file = profilePath ?? path.join(PROFILES_DIR, `${card.profile}.yaml`)
    if (profilePath === undefined && !existsSync(file)) {
        return { problems: [`profile: no shipped profile ${card.profile}; pass its file with --profile`] }
    }
    return readProfile(file)
}

function profileOf(read: Read): ProfileRead {
    if ('problem' in read) {
        return { problems: [read.problem] }
    }
    const profile = Profile.safeParse(read.value)
    return profile.success ? { profile: profile.data } : { problems: problemsOf(profile.error, 'profile') }
}

export function readProfile(file: string): ProfileRead {
    return profileOf(readYaml(file, 'profile'))
}

export function load(cardPath: string, options: LoadOptions = {}): LoadedCard {
    return check(cardPath, readYaml(cardPath, 'card'), (card) => loadProfile(card, options.profilePath), options.target)
}

export function loadText(label: string, { card, profile }: { card: string; profile: string }): LoadedCard {
    return check(
        label,
        parseYaml(() => card, 'card'),
        () => profileOf(parseYaml(() => profile, 'profile'))
    )
}

function check(
    cardPath: string,
    read: Read,
    profileFor: (card: Card) => ProfileRead,
    target: Target = 'local'
): LoadedCard {
    if ('problem' in read) {
        throw new CardError(cardPath, [read.problem])
    }
    const parsed = Card.safeParse(read.value)
    if (!parsed.success) {
        throw new CardError(cardPath, problemsOf(parsed.error, ''))
    }
    const card = parsed.data
    const loaded = profileFor(card)
    const defaults = getDefaultConfig() as unknown as Settings

    const problems = [
        ...checkNames(card, DEFINITIONS),
        ...checkSuppression(card),
        ...checkTrafficOnce(card),
        ...checkIntakeVerdict(card),
        ...('profile' in loaded
            ? [
                  ...checkProfile(card, loaded.profile, DEFINITIONS, defaults),
                  ...checkWorkflowRate(card, loaded.profile, defaults),
                  ...targetProblems(card, loaded.profile, target),
              ]
            : loaded.problems),
    ]
    if (problems.length > 0 || !('profile' in loaded)) {
        throw new CardError(cardPath, problems)
    }

    const profileHash = sha256(loaded.profile)
    return {
        card,
        profile: loaded.profile,
        profileHash,
        cardHash: sha256({ card: { ...card, gates: undefined }, profileHash }),
    }
}
