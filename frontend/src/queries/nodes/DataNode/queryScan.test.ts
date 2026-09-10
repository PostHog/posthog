import { QueryScanSummary, QueryScanWarning } from '~/queries/schema/schema-general'
import { DashboardTile, InsightShortId, QueryBasedInsightModel } from '~/types'

import {
    queryScanAssistantPrompt,
    queryScanDashboardSummary,
    queryScanStatLine,
    queryScanTileStatLine,
    resolveQueryScan,
    showQueryScanTag,
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
    clause: "event != 'x'",
    rows_read: 8_400_000_000,
    duration_ms: 19_000,
}

const START_DATE_FINDING: QueryScanWarning = {
    ...FINDING,
    kind: 'no_start_date',
    message: 'This query has no start date.',
    fix: 'Add a start date on `timestamp`.',
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

    it.each([
        ['a finding and advice on', [FINDING], true, true],
        ['a finding and advice off', [FINDING], false, false],
        ['advice on and no finding', [], true, false],
    ] as [string, QueryScanWarning[], boolean, boolean][])(
        'decides the tile tag for %s',
        (_label, findings, showAdvice, expected) => {
            expect(showQueryScanTag(findings, showAdvice)).toEqual(expected)
        }
    )

    it('numbers every finding in the assistant prompt and asks it to explore the data first', () => {
        const prompt = queryScanAssistantPrompt([FINDING, START_DATE_FINDING])

        expect(prompt).toContain(`1. ${FINDING.message} Suggested change: ${FINDING.fix}`)
        expect(prompt).toContain(`2. ${START_DATE_FINDING.message} Suggested change: ${START_DATE_FINDING.fix}`)
        expect(prompt).toContain('run exploratory queries')
        expect(prompt).toContain('-- fill in the events this question is about')
    })

    it('names only the insights whose last run has advice', () => {
        const { entries } = queryScanDashboardSummary([
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

    it('signs the slow tiles and their counts, ignoring tile order', () => {
        const first = tile(2, slowInsight('aaa', 'Active users', 2))
        const second = tile(10, slowInsight('bbb', 'Slow SQL', 1))

        expect(queryScanDashboardSummary([first, second]).signature).toEqual(
            queryScanDashboardSummary([second, first]).signature
        )
        expect(queryScanDashboardSummary([first, second]).signature).not.toEqual(
            queryScanDashboardSummary([first, tile(10, slowInsight('bbb', 'Slow SQL', 3))]).signature
        )
    })
})
