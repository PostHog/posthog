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
const READBACK_QUERY = `SELECT uuid FROM events WHERE event = '${SCORECARD_EVENT}' AND properties.run_id = {run_id} LIMIT 1`
const REQUEST_TIMEOUT_MS = 10_000

export type WriteOptions = { pollMs?: number; deadlineMs?: number }

export type WriteOutcome = { recorded: boolean; problem?: string }

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
    return response.status >= 200 && response.status < 300 ? undefined : `capture answered ${response.status}`
}

async function readBack(runId: string, { host, projectId, readKey }: Credentials): Promise<string | undefined> {
    const response = await internalFetch(`${host}/api/projects/${projectId}/query/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${readKey}` },
        body: JSON.stringify({ query: { kind: 'HogQLQuery', query: READBACK_QUERY, values: { run_id: runId } } }),
        timeoutMs: REQUEST_TIMEOUT_MS,
    })
    if (response.status !== 200) {
        await response.dump()
        return `the query answered ${response.status}`
    }
    const { results } = (await response.json()) as { results: unknown[] }
    return results.length > 0 ? undefined : 'the query did not return the event yet'
}

async function write(
    properties: ScorecardProperties,
    credentials: Credentials,
    { pollMs = 5000, deadlineMs = 120_000 }: WriteOptions
): Promise<WriteOutcome> {
    const target = { ...credentials, host: credentials.host.replace(/\/+$/, '') }
    const deadline = Date.now() + deadlineMs
    let captured = false
    let problem: string | undefined
    for (;;) {
        try {
            if (!captured) {
                problem = await capture(properties, target)
                captured = problem === undefined
            }
            if (captured) {
                problem = await readBack(properties.run_id, target)
                if (problem === undefined) {
                    return { recorded: true }
                }
            }
        } catch (error) {
            problem = (error as Error).message
        }
        const left = deadline - Date.now()
        if (left <= 0) {
            return {
                recorded: false,
                problem: `the scorecard was not read back within ${deadlineMs / 1000}s: ${problem}`,
            }
        }
        await sleep(Math.min(pollMs, left))
    }
}

export async function publish(
    properties: ScorecardProperties,
    env: NodeJS.ProcessEnv,
    options: WriteOptions = {}
): Promise<WriteOutcome> {
    const { credentials, problem } = credentialsOf(env)
    if (problem !== undefined) {
        return { recorded: false, problem }
    }
    return credentials ? await write(properties, credentials, options) : { recorded: false }
}
