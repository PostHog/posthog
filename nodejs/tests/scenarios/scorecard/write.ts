import { internalFetch } from '~/common/utils/request'
import { waitForExpect } from '~/tests/helpers/expectations'

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

async function readBack(runId: string, { host, projectId, readKey }: Credentials): Promise<string | undefined> {
    const response = await internalFetch(`${host}/api/projects/${projectId}/query/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${readKey}` },
        body: JSON.stringify({
            query: { kind: 'HogQLQuery', query: READBACK_QUERY, values: { run_id: runId } },
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

async function write(
    properties: ScorecardProperties,
    credentials: Credentials,
    { pollMs = 5000, deadlineMs = 120_000 }: WriteOptions
): Promise<WriteOutcome> {
    const target = { ...credentials, host: credentials.host.replace(/\/+$/, '') }
    let captured = false
    try {
        const refusal = await waitForExpect(
            async () => {
                if (!captured) {
                    const refused = await capture(properties, target)
                    if (refused !== undefined) {
                        return refused
                    }
                    captured = true
                }
                return await readBack(properties.run_id, target)
            },
            deadlineMs,
            pollMs
        )
        return refusal === undefined ? { recorded: true } : { recorded: false, problem: refusal }
    } catch (error) {
        return {
            recorded: false,
            problem: `the scorecard was not read back within ${deadlineMs / 1000}s: ${(error as Error).message}`,
        }
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
