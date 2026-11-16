import type { UsageSnapshotPayloadApi } from './generated/api.schemas'
import { buildSourceRows } from './usageRows'

const PAYLOAD: UsageSnapshotPayloadApi = {
    metric_runs: [
        {
            metric_id: 'm1',
            direct_runs: { web: 3, mcp: 5 },
            direct_people: 4,
            scout_runs: 120,
        },
    ],
    adjusted_runs: null,
    topics: null,
    topic_definitions: null,
    topic_sessions: null,
    table_sources: [{ name: 'revenue_daily', sessions: 2, people: 5 }],
    uncovered: null,
    proposed_metrics: null,
    failed_sections: [],
}

describe('buildSourceRows', () => {
    it('ranks tables and metrics by people, leaves out scout runs, and leaves out metrics with no run', () => {
        const rows = buildSourceRows(PAYLOAD, { m1: 'Signups' })

        expect(rows).toEqual([
            { key: 'table-revenue_daily', kind: 'table', name: 'revenue_daily', uses: 2, people: 5, surfaces: [] },
            {
                key: 'metric-m1',
                kind: 'metric',
                name: 'Signups',
                uses: 8,
                people: 4,
                surfaces: [
                    ['mcp', 5],
                    ['web', 3],
                ],
            },
        ])
    })

    it('keeps the top tables ahead of metrics that reach more people, and shows 25 rows', () => {
        const metricRun = (
            index: number
        ): UsageSnapshotPayloadApi['metric_runs'] extends (infer T)[] | null ? T : never => ({
            ...PAYLOAD.metric_runs![0],
            metric_id: `m${index}`,
            direct_people: 50 - index,
        })
        const rows = buildSourceRows(
            {
                ...PAYLOAD,
                metric_runs: Array.from({ length: 30 }, (_, index) => metricRun(index + 1)),
                table_sources: [
                    { name: 'small_a', sessions: 2, people: 2 },
                    { name: 'small_b', sessions: 1, people: 1 },
                ],
            },
            {}
        )

        expect(rows.slice(0, 5).map((row) => row.name)).toEqual(['m1', 'm2', 'm3', 'small_a', 'small_b'])
        expect(rows).toHaveLength(25)
        expect(rows[5].name).toBe('m4')
    })
})
