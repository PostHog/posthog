import { createHash } from 'crypto'
import { existsSync, readFileSync } from 'fs'
import path from 'path'
import { parse } from 'yaml'
import { z } from 'zod'

import { getDefaultCdpConfig } from '~/cdp/config'
import { stringToBoolean } from '~/common/utils/env-utils'

import { durationMs } from '../duration'
import { DEFINITIONS, Definition, Definitions } from './definitions'
import { Card, Named, Profile, RunningOnQueue } from './schema'

export const PROFILES_DIR = path.join(__dirname, '..', 'profiles')
export const ROLE_RESTART_BACKOFF_MS = 2000
const JANITOR_STALL_BACKOFF_FIRST_RETRY_SPREAD_MS = 5000
const STALLING_VALVES = ['role.kill', 'role.freeze', 'pg.drop_connections']

export type LoadedCard = { card: Card; profile: Profile; cardHash: string; profileHash: string }

export type LoadOptions = { profilePath?: string; definitions?: Definitions }

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

function readYaml(file: string, label: string): { value: unknown } | { problem: string } {
    if (!existsSync(file)) {
        return { problem: `${label}: no file at ${file}` }
    }
    try {
        return { value: parse(readFileSync(file, 'utf8'), { maxAliasCount: 0 }) }
    } catch (error) {
        return { problem: `${label}: ${(error as Error).message}` }
    }
}

function sortKeys(value: unknown): unknown {
    if (Array.isArray(value)) {
        return value.map(sortKeys)
    }
    if (value !== null && typeof value === 'object') {
        return Object.fromEntries(
            Object.keys(value)
                .sort()
                .map((key) => [key, sortKeys((value as Record<string, unknown>)[key])])
        )
    }
    return value
}

function sha256(value: unknown): string {
    return createHash('sha256')
        .update(JSON.stringify(sortKeys(value)))
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
        ...card.valves.flatMap((entry, i) => {
            const definition = definitions.valves.find(({ name }) => name === entry.valve)
            if (!definition) {
                return [`valves.${i}.valve: unknown valve ${entry.valve}`]
            }
            const dose = definition.params.safeParse(entry.dose)
            return dose.success ? [] : problemsOf(dose.error, `valves.${i}.dose`)
        }),
    ]
}

function checkSchedules(card: Card): string[] {
    return card.valves.flatMap((entry, i) => {
        if (entry.when && entry.when.name !== 'running_on_queue') {
            return [`valves.${i}.when.name: running_on_queue is the only predicate, not ${entry.when.name}`]
        }
        if (entry.when) {
            const params = RunningOnQueue.safeParse(entry.when.params)
            return params.success ? [] : problemsOf(params.error, `valves.${i}.when.params`)
        }
        if (entry.valve === 'pg.drop_connections') {
            return [`valves.${i}.at: pg.drop_connections waits for running jobs, so it takes when, not at`]
        }
        return []
    })
}

function checkStallBound(card: Card, setting: (name: string) => string): string[] {
    if (!card.valves.some(({ valve }) => STALLING_VALVES.includes(valve))) {
        return []
    }
    const milliseconds = (name: string): number => parseFloat(setting(name))
    const names = ['CYCLOTRON_NODE_JANITOR_STALL_TIMEOUT_MS', 'CYCLOTRON_NODE_JANITOR_CLEANUP_INTERVAL_MS']
    const unreadable = names.filter((name) => !(milliseconds(name) >= 0))
    if (unreadable.length > 0) {
        return unreadable.map((name) => `profile.settings.${name}: not a number of milliseconds`)
    }
    const stalls = card.valves.filter(({ valve }) => STALLING_VALVES.includes(valve)).length
    const baseMs = Math.max(milliseconds('CYCLOTRON_NODE_JANITOR_STALL_BACKOFF_BASE_MS'), 0) || 0
    const maxMs =
        milliseconds('CYCLOTRON_NODE_JANITOR_STALL_BACKOFF_MAX_MS') > 0
            ? milliseconds('CYCLOTRON_NODE_JANITOR_STALL_BACKOFF_MAX_MS')
            : 600000
    const boundMs =
        names.reduce((total, name) => total + milliseconds(name), 0) +
        JANITOR_STALL_BACKOFF_FIRST_RETRY_SPREAD_MS +
        Math.min(baseMs * (2 ** (stalls - 1) - 1), maxMs) +
        ROLE_RESTART_BACKOFF_MS
    if (durationMs(card.convergeWithin) > boundMs) {
        return []
    }
    return [
        `convergeWithin: ${card.convergeWithin} must exceed ${boundMs / 1000}s, the janitor's stall timeout, sweep interval, first-retry spread and repeated-stall backoff plus the role restart backoff`,
    ]
}

function checkSuppression(card: Card): string[] {
    const bounces = card.valves.some(({ valve, dose }) => valve === 'ses.reject' && dose.type === 'bounce')
    return card.invariants.flatMap(({ name }, i) =>
        name === 'bounced_suppressed' && !bounces
            ? [`invariants.${i}.name: bounced_suppressed needs a ses.reject entry with type bounce`]
            : []
    )
}

function checkProfile(card: Card, profile: Profile, definitions: Definitions, setting: (name: string) => string) {
    const queue = 'CDP_SES_WEBHOOKS_QUEUE_ENABLED'
    return [
        ...(profile.name === card.profile
            ? []
            : [`profile.name: ${profile.name} is not the card profile ${card.profile}`]),
        ...(stringToBoolean(setting(queue))
            ? [`profile.settings.${queue}: the queued SES feedback branch is not built yet, so it stays false`]
            : []),
        ...card.drive.traffic.flatMap(({ name }) => {
            const definition = definitions.traffic.find((traffic) => traffic.name === name)
            const traffic = definition?.profile.safeParse(profile.traffic[name])
            return traffic === undefined || traffic.success ? [] : problemsOf(traffic.error, `profile.traffic.${name}`)
        }),
    ]
}

function loadProfile(card: Card, profilePath: string | undefined): { profile: Profile } | { problems: string[] } {
    const file = profilePath ?? path.join(PROFILES_DIR, `${card.profile}.yaml`)
    if (profilePath === undefined && !existsSync(file)) {
        return { problems: [`profile: no shipped profile ${card.profile}; pass its file with --profile`] }
    }
    const read = readYaml(file, 'profile')
    if ('problem' in read) {
        return { problems: [read.problem] }
    }
    const profile = Profile.safeParse(read.value)
    return profile.success ? { profile: profile.data } : { problems: problemsOf(profile.error, 'profile') }
}

export function load(cardPath: string, options: LoadOptions = {}): LoadedCard {
    const definitions = options.definitions ?? DEFINITIONS
    const read = readYaml(cardPath, 'card')
    if ('problem' in read) {
        throw new CardError(cardPath, [read.problem])
    }
    const parsed = Card.safeParse(read.value)
    if (!parsed.success) {
        throw new CardError(cardPath, problemsOf(parsed.error, ''))
    }
    const card = parsed.data
    const loaded = loadProfile(card, options.profilePath)
    const defaults = getDefaultCdpConfig() as unknown as Record<string, unknown>
    const settings = 'profile' in loaded ? loaded.profile.settings : {}
    const setting = (name: string): string => settings[name] ?? String(defaults[name])

    const problems = [
        ...checkNames(card, definitions),
        ...checkSchedules(card),
        ...checkStallBound(card, setting),
        ...checkSuppression(card),
        ...('profile' in loaded ? checkProfile(card, loaded.profile, definitions, setting) : loaded.problems),
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
