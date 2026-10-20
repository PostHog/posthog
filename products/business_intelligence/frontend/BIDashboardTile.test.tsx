import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { BIConfig, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { insightOnDashboard, tileFromInsight } from '~/scenes/dashboard/dashboardLogic.testHelpers'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType, DashboardTile, InsightModel, InsightShortId } from '~/types'

import { biDashboardCrossFilterLogic } from './biDashboardCrossFilterLogic'
import { BIDashboardTile } from './BIDashboardTile'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'

describe('dashboard worksheet query execution', () => {
    afterEach(cleanup)

    it('loads the selected query and restores cached results without saving the worksheet', async () => {
        const requests: HogQLQuery[] = []
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const { query } = (await request.json()) as { query: HogQLQuery }
                    requests.push(query)
                    return [200, { columns: ['count'], types: [['count', 'Int64']], results: [[42]] }]
                },
            },
        })
        initKeaTests()
        const config: BIConfig = {
            ...DEFAULT_BI_CONFIG,
            source: { table: 'events' },
            chartType: ChartDisplayType.BoldNumber,
        }
        const query: BIVisualizationNode = {
            ...buildBIQuery(config)!.node,
            kind: NodeKind.BIVisualizationNode,
            config,
        }
        const insight: InsightModel = {
            ...insightOnDashboard(2, [777]),
            id: 2,
            short_id: 'target' as InsightShortId,
            name: 'Total',
            query,
            columns: ['count'],
            types: [['count', 'Int64']],
            result: [[160]],
        }
        const tiles: DashboardTile[] = [tileFromInsight(insight, 2)]
        const logic = biDashboardCrossFilterLogic({ dashboardId: 777, tiles })
        const unmount = logic.mount()
        logic.actions.setEnabled(true)
        const original = structuredClone(insight)
        const rendered = render(<BIDashboardTile dashboardId={777} tileId={2} insight={insight} query={query} />)
        try {
            await screen.findByText('160')
            expect(requests).toHaveLength(0)
            act(() =>
                logic.actions.setSelection({
                    tileId: 1,
                    title: 'Countries',
                    source: { table: 'events' },
                    selection: {
                        previous: false,
                        labels: [{ name: 'Country', value: 'US' }],
                        filters: [
                            {
                                field: {
                                    id: 'country',
                                    name: 'Country',
                                    expression: 'properties.country',
                                    type: 'string',
                                    source: { table: 'events' },
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
            expect(requests[0].query).toContain("properties.country = 'US'")
            act(() => logic.actions.setSelection(null))
            await waitFor(() => expect(screen.getByText('160')).toBeInTheDocument())
            expect(requests).toHaveLength(1)
            expect(insight).toEqual(original)
        } finally {
            rendered.unmount()
            unmount()
        }
    })
})
