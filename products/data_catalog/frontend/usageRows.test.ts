import type { AdjustedRunApi, UsageSnapshotPayloadApi } from './generated/api.schemas'
import { buildMetricUsageRows } from './usageRows'

function adjusted(metricId: string, outcome: AdjustedRunApi['fetch_outcome'], isScout: boolean): AdjustedRunApi {
    return {
        metric_id: metricId,
        fetch_outcome: outcome,
        relation: 'serves',
        intent: 'weekly signups',
        sql: 'select count() from events',
        reasoning: 'Same measure.',
        occurred_at: '2026-10-20T12:00:00Z',
        session_id: null,
        is_scout: isScout,
    }
}

const PAYLOAD: UsageSnapshotPayloadApi = {
    metric_runs: [
        {
            metric_id: 'm1',
            direct_runs: { web: 3, mcp: 5 },
            direct_people: 4,
            scout_runs: 120,
            source_insight_dashboard_runs: 0,
            source_insight_insight_runs: 0,
        },
    ],
    adjusted_runs: [adjusted('m1', 'adapted', false), adjusted('m1', 'silent', true), adjusted('m2', 'missed', false)],
    topics: null,
    uncovered: null,
    failed_sections: [],
}

describe('buildMetricUsageRows', () => {
    test.each([
        [
            false,
            { directRuns: 8, adapted: 1, silent: 0 },
            [
                ['mcp', 5],
                ['web', 3],
            ],
        ],
        [
            true,
            { directRuns: 128, adapted: 1, silent: 1 },
            [
                ['scouts', 120],
                ['mcp', 5],
                ['web', 3],
            ],
        ],
    ])('include scouts %s', (includeScouts, counts, surfaces) => {
        const rows = buildMetricUsageRows(PAYLOAD, { m1: 'Signups' }, includeScouts)

        expect(rows[0]).toMatchObject({ metricId: 'm1', name: 'Signups', people: 4, surfaces, ...counts })
        expect(rows[1]).toMatchObject({ metricId: 'm2', name: 'm2', directRuns: 0, missed: 1 })
    })
})
