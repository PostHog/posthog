import type { ChartSourceApi } from './generated/api.schemas'
import { proposedUsageSummary } from './proposedSources'

const NO_SOURCES = { people: 5, built: 30, viewed: 3, charts: [], other_charts: 0, surfaces: [], agents: null }

function chart(insightShortId: string, dashboardId: number | null): ChartSourceApi {
    return {
        insight_short_id: insightShortId,
        insight_name: insightShortId,
        dashboard_id: dashboardId,
        dashboard_name: dashboardId === null ? null : `Dashboard ${dashboardId}`,
        people: 1,
    }
}

describe('proposedUsageSummary', () => {
    test.each([
        ['falls back to the build count without sources', NO_SOURCES, '5 people · used 30 times'],
        [
            'counts each chart and each dashboard once and adds the charts it does not list',
            {
                ...NO_SOURCES,
                people: 14,
                charts: [chart('a', 7), chart('a', 8), chart('a', null), chart('b', 7)],
                other_charts: 2,
                surfaces: [{ product: 'sql_editor', people: 2, runs: 9 }],
                agents: { people: 6, sessions: 11, runs: 31 },
            },
            '14 people · 2 dashboards · 4 charts · 11 agent sessions · SQL editor',
        ],
    ])('%s', (_, usage, expected) => {
        // pluralize keeps a number and its noun together with a non-breaking space.
        expect(proposedUsageSummary(usage).replace(/\u00a0/g, ' ')).toEqual(expected)
    })
})
