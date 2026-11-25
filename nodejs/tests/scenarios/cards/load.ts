import { createHash } from 'crypto'
import { existsSync, readFileSync } from 'fs'
import path from 'path'
import { parse, stringify } from 'yaml'
import { z } from 'zod'

import { parseNumberFromEnv } from '~/common/config'
import { getDefaultConfig } from '~/common/config/config'

import { EMAIL_ACTION, TRAFFIC } from '../generator/traffic'
import { roleFreeze, roleKill } from '../valves/valves'
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

const INTAKE_TOPIC_MOVES =
    "convergence reads each intake group's whole lag, so an intake topic that changes between cards keeps the old topic's lag"
const REFUSED_INTAKE_SETTINGS: Record<string, string> = {
    CDP_INTAKE_DLQ_DRAIN:
        'the reset never seeks the drain groups and convergence never reads them, so a drain replays the dead-letter topic outside the verdict',
    CDP_INTAKE_TRANSACTIONAL_EMAIL_TOPIC: INTAKE_TOPIC_MOVES,
    CDP_INTAKE_WORKFLOW_WEBHOOK_TOPIC: INTAKE_TOPIC_MOVES,
}

function checkIntakeProfile(profile: Profile): string[] {
    return [
        ...Object.keys(profile.settings)
            .filter((name) => Object.hasOwn(REFUSED_INTAKE_SETTINGS, name))
            .map((name) => `profile.settings.${name}: ${REFUSED_INTAKE_SETTINGS[name]}`),
        ...Object.entries(profile.replicas)
            .filter(([role, replicas]) => role.startsWith('cdp-intake-') && (replicas ?? 1) > 1)
            .map(
                ([role]) =>
                    `profile.replicas.${role}: each intake topic has one partition, so a second replica sits idle; run one`
            ),
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
function settingOf(profile: Profile, defaults: Settings, key: string): number {
    const fallback = Number(defaults[key])
    const raw = profile.settings[key]
    return raw === undefined ? fallback : parseNumberFromEnv(key, String(raw), fallback)
}

const topScaleOf = (card: Card): number => Math.max(...stepsOf(card.drive).map(({ scale }) => scale))

function checkWorkflowRate(card: Card, profile: Profile, defaults: Settings): string[] {
    const ceiling = settingOf(profile, defaults, 'CDP_RATE_LIMITER_REFILL_RATE') * RATE_LIMIT_SHARE
    const topScale = topScaleOf(card)
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

const ROLE_STOPPING_VALVES = [roleKill.name, roleFreeze.name]

function checkIntakeReplicaValves(card: Card, profile: Profile): string[] {
    if ((profile.replicas['cdp-api'] ?? 1) === 1) {
        return []
    }
    return card.valves.flatMap(({ valve, target }, i) =>
        ROLE_STOPPING_VALVES.includes(valve) && target === 'cdp-api'
            ? [
                  `valves.${i}.target: ${valve} stops cdp-api replica 0 only, and the runner keeps sending every other request to it; run one cdp-api replica on this card`,
              ]
            : []
    )
}

const EMAIL_WORKER = 'cdp-cyclotron-worker-email'

const killsEmailWorker = ({ valve, target }: Card['valves'][number]): boolean =>
    valve === roleKill.name && target === EMAIL_WORKER

function checkAcceptedBoundary(card: Card): string[] {
    return card.valves.flatMap((entry, i) =>
        entry.when?.name === 'edge_accepted' && !killsEmailWorker(entry)
            ? [
                  `valves.${i}.when: edge_accepted holds an email worker's send, so it fires only role.kill on ${EMAIL_WORKER}`,
              ]
            : []
    )
}

function checkAcceptedBoundaryReplicas(card: Card, profile: Profile): string[] {
    if ((profile.replicas[EMAIL_WORKER] ?? 1) === 1) {
        return []
    }
    return card.valves.flatMap((entry, i) =>
        entry.when?.name === 'edge_accepted' && killsEmailWorker(entry)
            ? [
                  `valves.${i}.target: role.kill stops ${EMAIL_WORKER} replica 0 only, and edge_accepted can hold another replica's send; run one email worker replica on this card`,
              ]
            : []
    )
}

const SES_SHARE = 0.5

const withoutFloatNoise = (value: number): number => Number(value.toFixed(6))

function checkSesLimiter(card: Card, profile: Profile, defaults: Settings): string[] {
    const sendsEmail = card.drive.traffic.some(({ name }) =>
        TRAFFIC.find((traffic) => traffic.name === name)?.deliveries.includes(EMAIL_ACTION)
    )
    if (profile.load === undefined || !sendsEmail) {
        return []
    }
    const capacity = settingOf(profile, defaults, 'CDP_SES_RATE_LIMIT_CAPACITY')
    const replicas = profile.replicas['cdp-cyclotron-worker-email'] ?? 1
    const burst = replicas * settingOf(profile, defaults, 'CONSUMER_BATCH_SIZE')
    return [
        ...checkSesRefill(card, profile, defaults, profile.load.targets.claimsPerSecond.email, profile.load.tolerance),
        ...(capacity >= burst
            ? []
            : [
                  `profile.settings.CDP_SES_RATE_LIMIT_CAPACITY: ${capacity} cannot hold one batch for every email replica (${replicas}) at once; raise it to ${burst} or more`,
              ]),
    ]
}

function checkSesRefill(
    card: Card,
    profile: Profile,
    defaults: Settings,
    claims: number | undefined,
    tolerance: number
): string[] {
    if (claims === undefined) {
        return ['profile.load.targets.claimsPerSecond.email: the SES limiter check needs it']
    }
    const topScale = topScaleOf(card)
    const peak = withoutFloatNoise(claims * topScale * (1 + tolerance))
    const ceiling = settingOf(profile, defaults, 'CDP_SES_RATE_LIMIT_REFILL_PER_SECOND') * SES_SHARE
    return peak <= ceiling
        ? []
        : [
              `profile.settings.CDP_SES_RATE_LIMIT_REFILL_PER_SECOND: the email queue claims up to ${Math.ceil(peak)} jobs a second at the ${topScale}x step, over ${ceiling}, ${SES_SHARE * 100}% of the SES limiter refill; raise it to ${Math.ceil(peak / SES_SHARE)} or more`,
          ]
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
        ...checkAcceptedBoundary(card),
        ...('profile' in loaded
            ? [
                  ...checkProfile(card, loaded.profile, DEFINITIONS, defaults),
                  ...checkWorkflowRate(card, loaded.profile, defaults),
                  ...checkSesLimiter(card, loaded.profile, defaults),
                  ...checkIntakeReplicaValves(card, loaded.profile),
                  ...checkAcceptedBoundaryReplicas(card, loaded.profile),
                  ...checkIntakeProfile(loaded.profile),
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
        cardHash: cardHashOf(card, profileHash),
    }
}

export const cardHashOf = (card: Card, profileHash: string): string =>
    sha256({ card: { ...card, gates: undefined }, profileHash })
