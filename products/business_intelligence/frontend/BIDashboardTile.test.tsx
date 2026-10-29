import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'

import { InsightCard } from 'lib/components/Cards/InsightCard/InsightCard'

import { useMocks } from '~/mocks/jest'
import { BIConfig, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { HogQLQuery, NodeKind, RefreshType } from '~/queries/schema/schema-general'
import { insightOnDashboard, tileFromInsight } from '~/scenes/dashboard/dashboardLogic.testHelpers'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType, DashboardPlacement, DashboardTile, InsightModel, InsightShortId } from '~/types'

import { biDashboardCrossFilterLogic } from './biDashboardCrossFilterLogic'
import { BIDashboardTile } from './BIDashboardTile'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'

describe('dashboard worksheet query execution', () => {
    afterEach(cleanup)

    it.each(['tile', 'card'])(
        'refreshes filtered results and preserves resolved filters and metadata in the %s',
        async (surface) => {
            const requests: { query: HogQLQuery; refresh: RefreshType }[] = []
            const alertInsightIds: string[] = []
            useMocks({
                get: {
                    '/api/projects/:team_id/alerts/': ({ request }) => {
                        alertInsightIds.push(new URL(request.url).searchParams.get('insight_id')!)
                        return [200, { results: [] }]
                    },
                },
                post: {
                    '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                        requests.push((await request.json()) as { query: HogQLQuery; refresh: RefreshType })
                        return [
                            200,
                            { columns: ['count'], types: [['count', 'Int64']], results: [[42 * requests.length]] },
                        ]
                    },
                },
            })
            initKeaTests()
            const config: BIConfig = {
                ...DEFAULT_BI_CONFIG,
                source: { table: 'orders' },
                chartType: ChartDisplayType.BoldNumber,
            }
            const query: BIVisualizationNode = {
                ...buildBIQuery(config)!.node,
                kind: NodeKind.BIVisualizationNode,
                config,
            }
            query.source.filters = { dateRange: { date_from: '-30d' }, properties: [] }
            query.source.variables = { plan: { variableId: 'plan', code_name: 'plan', value: 'pro' } }
            const insight: InsightModel = {
                ...insightOnDashboard(2, [777]),
                id: 2,
                short_id: 'target' as InsightShortId,
                name: 'Total',
                query,
                columns: ['count'],
                types: [['count', 'Int64']],
                result: [[160]],
                last_refresh: '2026-01-01T00:00:00Z',
                alerts: undefined,
            }
            const source = tileFromInsight({ ...insight, id: 1, short_id: 'source' as InsightShortId }, 1)
            const tiles: DashboardTile[] = [source, tileFromInsight(insight, 2)]
            const logic = biDashboardCrossFilterLogic({ dashboardId: 777, tiles })
            const unmount = logic.mount()
            const original = structuredClone(insight)
            const card = (insight: InsightModel): JSX.Element =>
                surface === 'tile' ? (
                    <BIDashboardTile dashboardId={777} tileId={2} insight={insight} query={query} />
                ) : (
                    <InsightCard
                        dashboardId={777}
                        biDashboardTileId={2}
                        insight={insight}
                        placement={DashboardPlacement.Dashboard}
                        renderVizWhenMounted
                        filtersOverride={{ date_from: '-7d', filterTestAccounts: true }}
                        variablesOverride={{ plan: { variableId: 'plan', code_name: 'plan', value: 'free' } }}
                    />
                )
            const rendered = render(card(insight))
            try {
                await screen.findByText('160')
                expect(requests).toHaveLength(0)
                if (surface === 'tile') {
                    await waitFor(() => expect(alertInsightIds).toEqual(['2']))
                }
                act(() =>
                    logic.actions.setSelection({
                        tileId: 1,
                        title: 'Countries',
                        source: { table: 'orders' },
                        selection: {
                            previous: false,
                            labels: [{ name: 'Country', value: 'US' }],
                            filters: [
                                {
                                    field: {
                                        id: 'country',
                                        name: 'Country',
                                        expression: 'country',
                                        type: 'string',
                                        source: { table: 'orders' },
                                    },
                                    operator: 'equals',
                                    value: 'US',
                                },
                            ],
                        },
                    })
                )
                await screen.findByText('42')
                expect(requests).toHaveLength(1)
                expect(requests[0].query.query).toContain("country = 'US'")
                expect(requests[0].query.filters).toEqual(query.source.filters)
                expect(requests[0].query.variables).toEqual(query.source.variables)
                const refreshedInsight = { ...insight, result: [[200]], last_refresh: '2026-01-01T00:01:00Z' }
                act(() => {
                    biDashboardCrossFilterLogic({
                        dashboardId: 777,
                        tiles: [source, tileFromInsight(refreshedInsight, 2)],
                    })
                })
                rendered.rerender(card(refreshedInsight))
                await screen.findByText('84')
                expect(requests).toHaveLength(2)
                expect(requests[1]).toMatchObject({ query: requests[0].query, refresh: 'force_blocking' })
                expect(alertInsightIds.every((id) => id === '2')).toBe(true)
                act(() => logic.actions.setSelection(null))
                await waitFor(() => expect(screen.getByText('200')).toBeInTheDocument())
                expect(requests).toHaveLength(2)
                expect(insight).toEqual(original)
            } finally {
                rendered.unmount()
                unmount()
            }
        }
    )
})
