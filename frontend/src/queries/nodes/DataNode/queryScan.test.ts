import { QueryScanSummary, QueryScanWarning } from '~/queries/schema/schema-general'
import { DashboardTile, InsightShortId, InsightModel } from '~/types'

import {
    QueryScanPollResult,
    queryScanDashboardEntries,
    queryScanStatLine,
    queryScanTileStatLine,
    resolveQueryScan,
} from './queryScan'

const SUMMARY: QueryScanSummary = {
    rows_read: 8_400_000_000,
    duration_ms: 19_000,
    analysis_requested: true,
}

const FINDING: QueryScanWarning = {
    kind: 'no_event_filter',
    message: 'This query read every event in its date range.',
    fix: 'Add an event filter naming the events this question is about.',
    actionable: true,
}

// A by-design finding explains the read and leaves the person nothing to change.
const BY_DESIGN_FINDING: QueryScanWarning = {
    kind: 'no_start_date',
    by_design: true,
    message: 'This query finds a first event ever, so it reads all your data by design.',
    fix: 'Do not propose a time bound for that read.',
    actionable: false,
}

function tile(id: number, insight: Partial<InsightModel> | null): DashboardTile {
    return { id, color: null, insight: insight ? (insight as InsightModel) : undefined }
}

function slowInsight(
    shortId: string,
    name: string,
    findings: QueryScanWarning[],
    summary: Partial<QueryScanSummary> = {}
): Partial<InsightModel> {
    return {
        short_id: shortId as InsightShortId,
        name,
        query_scan: { ...SUMMARY, ...summary, analysis: { findings } },
    }
}

describe('queryScan', () => {
    it('reads no scan off a response that carries no summary', () => {
        expect(resolveQueryScan({ results: [] }, null, null)).toBeNull()
    })

    it('ignores a poll result for another run', () => {
        // A poll outlives the run that started it, so a result for another run must not decorate
        // this response with a share and advice measured somewhere else.
        const response = { query_scan: SUMMARY, cache_key: 'cache-key' }
        const polled: QueryScanPollResult = {
            cacheKey: 'another-cache-key',
            analysis: { findings: [FINDING], range_share: 0.9, project_share: 0.9 },
        }

        const state = resolveQueryScan(response, null, polled)

        expect(state?.summary.analysis).toBeUndefined()
        expect(state?.findings).toHaveLength(0)
    })

    it.each([
        ['a run that finished', {}, 'Read 8,400,000,000 rows in 19.0 s.'],
        [
            'a run whose analysis measured the share of the date range it read',
            { analysis: { findings: [], range_share: 0.42 } },
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

    it('names only the insights whose last run has advice the viewer can act on', () => {
        const entries = queryScanDashboardEntries([
            tile(1, null),
            tile(2, slowInsight('aaa', 'Active users', [FINDING, FINDING])),
            tile(3, slowInsight('bbb', 'Fast enough', [])),
            tile(4, { short_id: 'ccc' as InsightShortId, name: 'Still analyzing', query_scan: SUMMARY }),
            tile(5, { ...slowInsight('ddd', 'Deleted', [FINDING]), deleted: true }),
            tile(6, { short_id: 'eee' as InsightShortId, derived_name: 'Never run' }),
            tile(7, { ...slowInsight('fff', '', [FINDING]), derived_name: 'Pageview count' }),
            tile(8, slowInsight('ggg', '', [FINDING])),
            // Reads all history by design: nothing for the banner to send the viewer to change.
            tile(9, slowInsight('hhh', 'First purchases', [BY_DESIGN_FINDING])),
            tile(10, slowInsight('iii', 'Mixed', [BY_DESIGN_FINDING, FINDING])),
        ])

        expect(entries).toEqual([
            { tileId: 2, shortId: 'aaa', name: 'Active users', findingCount: 2 },
            { tileId: 7, shortId: 'fff', name: 'Pageview count', findingCount: 1 },
            { tileId: 8, shortId: 'ggg', name: 'Untitled', findingCount: 1 },
            { tileId: 10, shortId: 'iii', name: 'Mixed', findingCount: 1 },
        ])
    })
})
