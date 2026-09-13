import { QueryScanSummary, QueryScanWarning } from '~/queries/schema/schema-general'
import { DashboardTile, InsightShortId, QueryBasedInsightModel } from '~/types'

import {
    QueryScanPollResult,
    queryScanDashboardEntries,
    queryScanStatLine,
    queryScanTileStatLine,
    resolveQueryScan,
} from './queryScan'

const SUMMARY: QueryScanSummary = {
    mode: 'show',
    rows_read: 8_400_000_000,
    duration_ms: 19_000,
    status: 'done',
}

const FINDING: QueryScanWarning = {
    type: 'query_scan',
    kind: 'no_event_filter',
    message: 'This query read every event in its date range.',
    fix: 'Add an event filter naming the events this question is about.',
}

function tile(id: number, insight: Partial<QueryBasedInsightModel> | null): DashboardTile<QueryBasedInsightModel> {
    return { id, color: null, insight: insight ? (insight as QueryBasedInsightModel) : undefined }
}

function slowInsight(
    shortId: string,
    name: string,
    findings: number,
    summary: Partial<QueryScanSummary> = {}
): Partial<QueryBasedInsightModel> {
    return {
        short_id: shortId as InsightShortId,
        name,
        query_scan: { ...SUMMARY, ...summary, warnings: Array(findings).fill(FINDING) },
    }
}

describe('queryScan', () => {
    it('reads no scan off a run the team only logs', () => {
        expect(resolveQueryScan({ query_scan: { ...SUMMARY, mode: 'log_only' } }, null, null)).toBeNull()
    })

    it('ignores a poll result for another run', () => {
        // A poll outlives the run that started it, so a result for another run must not decorate
        // this response with a share and advice measured somewhere else.
        const response = { query_scan: { ...SUMMARY, status: 'pending' }, cache_key: 'cache-key', warnings: [] }
        const polled: QueryScanPollResult = {
            cacheKey: 'another-cache-key',
            scan: { status: 'done', warnings: [FINDING], range_share: 0.9, project_share: 0.9, killed: false },
        }

        const state = resolveQueryScan(response, null, polled)

        expect(state?.summary.status).toBe('pending')
        expect(state?.findings).toHaveLength(0)
    })

    it.each([
        ['a run that finished', {}, 'Read 8,400,000,000 rows in 19.0 s.'],
        [
            'a run whose analysis measured the share of the date range it read',
            { range_share: 0.42 },
            'Read 8,400,000,000 rows in 19.0 s, about 42% of the events in this date range.',
        ],
        [
            'a run ClickHouse stopped',
            { killed: true },
            'ClickHouse stopped it after 19.0 s, having read 8,400,000,000 rows.',
        ],
    ] as [string, Partial<QueryScanSummary>, string][])('describes %s', (_label, summary, expected) => {
        expect(queryScanStatLine({ ...SUMMARY, ...summary })).toEqual(expected)
    })

    it.each([
        ['a run that finished', {}, 'This tile read 8,400,000,000 rows in 19.0 s on its last run.'],
        [
            'a run ClickHouse stopped',
            { killed: true },
            "ClickHouse stopped this tile's last run after 19.0 s, having read 8,400,000,000 rows.",
        ],
    ] as [string, Partial<QueryScanSummary>, string][])('describes %s on a tile', (_label, summary, expected) => {
        expect(queryScanTileStatLine({ ...SUMMARY, ...summary })).toEqual(expected)
    })

    it('names only the insights whose last run has advice', () => {
        const entries = queryScanDashboardEntries([
            tile(1, null),
            tile(2, slowInsight('aaa', 'Active users', 2)),
            tile(3, slowInsight('bbb', 'Fast enough', 0)),
            tile(4, slowInsight('ccc', 'Only logging', 1, { mode: 'log_only' })),
            tile(5, { ...slowInsight('ddd', 'Deleted', 1), deleted: true }),
            tile(6, { short_id: 'eee' as InsightShortId, derived_name: 'Never run' }),
            tile(7, { ...slowInsight('fff', '', 1), derived_name: 'Pageview count' }),
            tile(8, slowInsight('ggg', '', 1)),
        ])

        expect(entries).toEqual([
            { tileId: 2, shortId: 'aaa', name: 'Active users', findingCount: 2 },
            { tileId: 7, shortId: 'fff', name: 'Pageview count', findingCount: 1 },
            { tileId: 8, shortId: 'ggg', name: 'Untitled', findingCount: 1 },
        ])
    })
})
