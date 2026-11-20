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

export async function unfinishedRuns(config: DevConfig, since: string): Promise<number> {
    const { teamId, workflowId } = config.offers
    const names = 'triggered,fetch,failed,quota_limited'
    const { series } = (await devFetch(
        `${config.host}/api/projects/${teamId}/hog_flows/${workflowId}/metrics/?after=${since}&interval=hour&breakdown_by=name&name=${names}`,
        { headers: { authorization: `Bearer ${config.key}` } },
        'workflow metrics read'
    )) as { series: { name: string; values: number[] }[] }
    const total = (name: string): number =>
        series.find((entry) => entry.name === name)?.values.reduce((sum, value) => sum + value, 0) ?? 0
    return Math.max(0, total('triggered') - total('fetch') - total('failed') - total('quota_limited'))
}
