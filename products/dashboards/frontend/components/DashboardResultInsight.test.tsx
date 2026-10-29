import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'

import { InsightCard } from 'lib/components/Cards/InsightCard/InsightCard'

import { useMocks } from '~/mocks/jest'
import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { insightOnDashboard, tileFromInsight } from '~/scenes/dashboard/dashboardLogic.testHelpers'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType, DashboardPlacement, InsightShortId } from '~/types'

import { dashboardResultFilterLogic } from '../dashboardResultFilterLogic'

describe('dashboard result insight execution', () => {
    afterEach(cleanup)

    it('filters and refreshes the target, preserves metadata, and restores its saved results when cleared', async () => {
        const result = (value: number): Record<string, unknown>[] => [
            {
                action: { id: '$pageview', type: 'events' },
                label: '$pageview',
                count: value,
                aggregated_value: value,
                data: [value],
                days: ['2026-01-01'],
                labels: ['1-Jan-2026'],
            },
        ]
        const requests: { query: TrendsQuery; refresh: string; filters_override?: unknown }[] = []
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    requests.push((await request.json()) as { query: TrendsQuery; refresh: string })
                    return [200, { results: result(42 * requests.length) }]
                },
            },
        })
        initKeaTests()
        const query: InsightVizNode<TrendsQuery> = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                dateRange: { date_from: '-7d' },
                breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                trendsFilter: { display: ChartDisplayType.BoldNumber },
            },
        }
        const insight = {
            ...insightOnDashboard(2, [777]),
            id: 2,
            short_id: 'target' as InsightShortId,
            query,
            result: result(160),
            last_refresh: '2026-01-01T00:00:00Z',
        }
        const source = tileFromInsight({ ...insight, id: 1, short_id: 'source' as InsightShortId }, 1)
        const tile = tileFromInsight(insight, 2)
        const logic = dashboardResultFilterLogic({ dashboardId: 777, tiles: [source, tile] })
        const unmount = logic.mount()
        try {
            render(
                <InsightCard
                    insight={insight}
                    tile={tile}
                    dashboardId={777}
                    biDashboardTileId={2}
                    resultMenuEnabled
                    renderVizWhenMounted
                    placement={DashboardPlacement.Dashboard}
                    filtersOverride={{
                        date_from: '-30d',
                        breakdown_filter: { breakdown: '$os', breakdown_type: 'event' },
                    }}
                />
            )
            await screen.findByText('160')
            expect(requests).toHaveLength(0)
            act(() =>
                logic.actions.selectResult({
                    dashboardId: 777,
                    tileId: 1,
                    label: 'Selected people',
                    query: {
                        kind: NodeKind.ActorsQuery,
                        source: { kind: NodeKind.InsightActorsQuery, source: query.source, day: '2026-01-01' },
                    },
                })
            )
            await waitFor(() => expect(requests).toHaveLength(1))
            await screen.findByText('42')
            expect(screen.getByText('Filtered by selection')).toBeInTheDocument()
            expect(requests[0].query).toMatchObject({
                dateRange: query.source.dateRange,
                breakdownFilter: query.source.breakdownFilter,
                properties: [expect.objectContaining({ key: expect.stringContaining('matchesInsight(') })],
            })
            expect(requests[0].filters_override).toBeUndefined()
            act(() => {
                dashboardResultFilterLogic({
                    dashboardId: 777,
                    tiles: [source, { ...tile, insight: { ...insight, last_refresh: '2026-01-01T00:01:00Z' } }],
                })
            })
            await screen.findByText('84')
            expect(requests[1]).toMatchObject({ refresh: 'force_blocking', query: requests[0].query })
            act(() => logic.actions.setSelection(null))
            await waitFor(() => expect(screen.getByText('160')).toBeInTheDocument())
            expect(insight.result).toEqual(result(160))
        } finally {
            unmount()
        }
    })
})
