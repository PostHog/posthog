import { setTimeout as sleep } from 'timers/promises'

import { internalFetch } from '~/common/utils/request'

import type { ScorecardProperties } from './scorecard'

export const CREDENTIALS = {
    host: 'SCENARIO_RUNS_HOST',
    projectId: 'SCENARIO_RUNS_PROJECT_ID',
    token: 'SCENARIO_RUNS_PROJECT_TOKEN',
    readKey: 'SCENARIO_RUNS_READ_KEY',
} as const

export type Credentials = Record<keyof typeof CREDENTIALS, string>

export const SCORECARD_EVENT = 'scorecard'
export const SCORECARD_DISTINCT_ID = 'scenario-runner'
const READBACK_QUERY = `SELECT uuid FROM events WHERE event = '${SCORECARD_EVENT}' AND properties.run_id = {run_id} AND timestamp >= toDateTime({from}, 'UTC') AND timestamp <= toDateTime({to}, 'UTC') LIMIT 1`
const READBACK_WINDOW_MS = 24 * 60 * 60 * 1000
const REQUEST_TIMEOUT_MS = 10_000

export type WriteOptions = { pollMs?: number; deadlineMs?: number }

export type WriteOutcome = { recorded: boolean; captured?: true; problem?: string }

export function credentialsOf(env: NodeJS.ProcessEnv): { credentials?: Credentials; problem?: string } {
    const keys = Object.keys(CREDENTIALS) as (keyof Credentials)[]
    const missing = keys.filter((key) => !env[CREDENTIALS[key]]).map((key) => CREDENTIALS[key])
    if (missing.length === keys.length) {
        return {}
    }
    if (missing.length > 0) {
        return {
            problem: `Scorecard credentials are set only in part; set all of them or none. Missing: ${missing.join(', ')}`,
        }
    }
    return { credentials: Object.fromEntries(keys.map((key) => [key, env[CREDENTIALS[key]]!])) as Credentials }
}

function refusalOf(status: number, answering: string, credential: string): string {
    if (status >= 400 && status < 500 && status !== 429) {
        return `${answering} answered ${status}; check ${credential}`
    }
    throw new Error(`${answering} answered ${status}`)
}

async function capture(properties: ScorecardProperties, { host, token }: Credentials): Promise<string | undefined> {
    const response = await internalFetch(`${host}/i/v0/e/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            api_key: token,
            event: SCORECARD_EVENT,
            distinct_id: SCORECARD_DISTINCT_ID,
            uuid: properties.run_id,
            timestamp: properties.ended_at,
            properties,
        }),
        timeoutMs: REQUEST_TIMEOUT_MS,
    })
    await response.dump()
    return response.status >= 200 && response.status < 300
        ? undefined
        : refusalOf(response.status, 'capture', CREDENTIALS.token)
}

async function readBack(
    { run_id, ended_at }: ScorecardProperties,
    { host, projectId, readKey }: Credentials
): Promise<string | undefined> {
    const endedAt = Date.parse(String(ended_at))
    const response = await internalFetch(`${host}/api/projects/${projectId}/query/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${readKey}` },
        body: JSON.stringify({
            query: {
                kind: 'HogQLQuery',
                query: READBACK_QUERY,
                values: {
                    run_id,
                    from: new Date(endedAt - READBACK_WINDOW_MS).toISOString(),
                    to: new Date(endedAt + READBACK_WINDOW_MS).toISOString(),
                },
            },
            refresh: 'force_blocking',
        }),
        timeoutMs: REQUEST_TIMEOUT_MS,
    })
    if (response.status !== 200) {
        await response.dump()
        return refusalOf(response.status, 'the query', CREDENTIALS.readKey)
    }
    const { results } = (await response.json()) as { results: unknown[] }
    if (results.length === 0) {
        throw new Error('the query did not return the event yet')
    }
    return undefined
}

function interrupted(captured: boolean, error: unknown): WriteOutcome {
    return captured
        ? { recorded: false, captured: true }
        : {
              recorded: false,
              problem: `the run was interrupted before the scorecard was captured: ${(error as Error).message}`,
          }
}

async function write(
    properties: ScorecardProperties,
    credentials: Credentials,
    signal: AbortSignal,
    { pollMs = 5000, deadlineMs = 120_000 }: WriteOptions
): Promise<WriteOutcome> {
    const target = { ...credentials, host: credentials.host.replace(/\/+$/, '') }
    const start = Date.now()
    let captured = false
    for (;;) {
        try {
            if (!captured) {
                const refused = await capture(properties, target)
                if (refused !== undefined) {
                    return { recorded: false, problem: refused }
                }
                captured = true
            }
            if (signal.aborted) {
                return { recorded: false, captured: true }
            }
            const refused = await readBack(properties, target)
            return refused === undefined ? { recorded: true } : { recorded: false, problem: refused }
        } catch (error) {
            if (signal.aborted) {
                return interrupted(captured, error)
            }
            if (Date.now() - start > deadlineMs) {
                return {
                    recorded: false,
                    problem: `the scorecard was not read back within ${deadlineMs / 1000}s: ${(error as Error).message}`,
                }
            }
            try {
                await sleep(pollMs, undefined, { signal })
            } catch {
                return interrupted(captured, error)
            }
        }
    }
}

export async function publish(
    properties: ScorecardProperties,
    env: NodeJS.ProcessEnv,
    signal: AbortSignal,
    options: WriteOptions = {}
): Promise<WriteOutcome> {
    const { credentials, problem } = credentialsOf(env)
    if (problem !== undefined) {
        return { recorded: false, problem }
    }
    return credentials ? await write(properties, credentials, signal, options) : { recorded: false }
}
