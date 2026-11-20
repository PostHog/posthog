import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import { WEBHOOK_ACTION } from '../generator/traffic'
import type { TruthRead, TruthSource } from '../judge/truth'
import { TRUTH_PAGE_LIMIT, TruthRecord } from '../provider-edge/truth'
import type { DevConfig } from './config'

// The query API lets one personal API key make 120 calls an hour.
export const QUERY_EVERY_MS = 30_000
// Above the dev unit cap, so a full answer means receipts went unread rather than a run that delivered this many.
export const RECEIPT_ROWS = 5000

const RECEIPTS = `select properties.unit_id, toUnixTimestamp64Milli(timestamp), uuid from events
where event = 'scenario_receipt' and properties.run_id = {run_id} and timestamp > now() - interval 1 day
order by timestamp, uuid limit ${RECEIPT_ROWS}`

async function devFetch(url: string, init: Parameters<typeof internalFetch>[1], what: string): Promise<unknown> {
    const response = await internalFetch(url, init)
    if (response.status !== 200) {
        throw new Error(`dev answered the ${what} with ${response.status}`)
    }
    const text = await response.text()
    try {
        return parseJSON(text)
    } catch {
        throw new Error(`dev answered the ${what} with a body that is not JSON`)
    }
}

export function receiptTruth(config: DevConfig, runId: string, now = Date.now): TruthSource {
    const records: TruthRecord[] = []
    const seen = new Set<string>()
    let readAt = -Infinity
    // A caller that bounds its wait, the live log, reads the last answer, so the judge owns each query and its errors.
    const refresh = async (read?: TruthRead): Promise<void> => {
        if (read?.timeoutMs !== undefined || now() - readAt < QUERY_EVERY_MS) {
            return
        }
        readAt = now()
        const { results } = (await devFetch(
            `${config.host}/api/projects/${config.receiptsTeamId}/query/`,
            {
                method: 'POST',
                headers: { authorization: `Bearer ${config.key}`, 'content-type': 'application/json' },
                body: JSON.stringify({
                    query: { kind: 'HogQLQuery', query: RECEIPTS, values: { run_id: runId } },
                    refresh: 'force_blocking',
                }),
            },
            'receipts query'
        )) as { results: [string, number, string][] }
        if (results.length >= RECEIPT_ROWS) {
            throw new Error(`the receipts query filled all ${RECEIPT_ROWS} rows, so some receipts went unread`)
        }
        for (const [unitId, at, uuid] of results) {
            if (seen.has(uuid)) {
                continue
            }
            seen.add(uuid)
            const seq = records.length + 1
            records.push({
                seq,
                at: new Date(at).toISOString(),
                kind: 'webhook',
                unitId,
                actionId: WEBHOOK_ACTION,
                status: 200,
                detail: {},
            })
        }
    }
    return {
        head: async (read) => {
            await refresh(read)
            return records.length
        },
        after: async (cursor, read) => {
            await refresh(read)
            const page = records.slice(cursor, cursor + (read?.limit ?? TRUTH_PAGE_LIMIT))
            return { records: page, next: page.at(-1)?.seq ?? cursor }
        },
    }
}

export type WorkflowRuns = Record<'triggered' | 'exited' | 'quota_limited', number>

async function metricsRead(config: DevConfig, query: Record<string, string>): Promise<(name: string) => number> {
    const { teamId, workflowId } = config.offers
    const params = new URLSearchParams({ breakdown_by: 'name', ...query })
    const { series } = (await devFetch(
        `${config.host}/api/projects/${teamId}/hog_flows/${workflowId}/metrics/?${params}`,
        { headers: { authorization: `Bearer ${config.key}` } },
        'workflow metrics read'
    )) as { series?: { name: string; values: unknown[] }[] }
    return (name) => {
        const values = series?.find((entry) => entry.name === name)?.values
        if (!values?.every((value) => Number.isFinite(value))) {
            throw new Error(`dev answered the workflow metrics read without a count of ${name}`)
        }
        return (values as number[]).reduce((sum, value) => sum + value, 0)
    }
}

// Every action counts a run as succeeded, and a quota limited run never counts as triggered, so a run of a workflow
// that ends only at its one exit, which `exitActionOf` checks, is finished once that exit counts it.
export async function workflowRuns(
    config: DevConfig,
    after: string,
    interval: 'hour' | 'day',
    exitId?: string
): Promise<WorkflowRuns> {
    const [runs, exits] = await Promise.all([
        metricsRead(config, { after, interval, name: 'triggered,quota_limited' }),
        exitId ? metricsRead(config, { after, interval, name: 'succeeded', instance_id: exitId }) : undefined,
    ])
    return { triggered: runs('triggered'), exited: exits?.('succeeded') ?? 0, quota_limited: runs('quota_limited') }
}

export const unfinishedOf = (runs: WorkflowRuns): number => Math.max(0, runs.triggered - runs.exited)

export async function exitActionOf(config: DevConfig): Promise<string> {
    const { teamId, workflowId } = config.offers
    const { actions = [], exit_condition } = (await devFetch(
        `${config.host}/api/projects/${teamId}/hog_flows/${workflowId}/`,
        { headers: { authorization: `Bearer ${config.key}` } },
        'workflow read'
    )) as { actions?: { id: string; type: string; on_error?: string | null }[]; exit_condition?: string }
    const exits = actions.filter(({ type }) => type === 'exit')
    if (
        exits.length !== 1 ||
        actions.some(({ on_error }) => on_error === 'abort') ||
        exit_condition !== 'exit_only_at_end'
    ) {
        throw new Error(
            'the workflow needs one exit action, no action that aborts, and exit_only_at_end, so the runner can count its finished runs'
        )
    }
    return exits[0].id
}

export async function checkOffersToken(config: DevConfig): Promise<void> {
    const { teamId, token } = config.offers
    const { api_token, timezone } = (await devFetch(
        `${config.host}/api/projects/${teamId}/`,
        { headers: { authorization: `Bearer ${config.key}` } },
        'offers project read'
    )) as { api_token?: string; timezone?: string }
    if (api_token !== token) {
        throw new Error(`DEV_TARGET_OFFERS_TOKEN is not the token of project ${teamId}, so offers would land elsewhere`)
    }
    if (timezone !== 'UTC') {
        throw new Error(`project ${teamId} is not on UTC, so its workflow metrics would be read for the wrong hours`)
    }
}
