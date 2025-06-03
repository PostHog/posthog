import { IconPageChart } from '@posthog/icons'
import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DashboardType, InsightShortId, QueryBasedInsightModel } from '~/types'

import { maxContextLogic } from './maxContextLogic'
import { maxMocks } from './testUtils'

describe('maxContextLogic', () => {
    let logic: ReturnType<typeof maxContextLogic.build>

    const mockInsight: Partial<QueryBasedInsightModel> = {
        short_id: 'insight-1' as InsightShortId,
        name: 'Test Insight',
        description: 'Test insight description',
        query: {
            source: { kind: 'TrendsQuery' },
        } as any,
    }

    const mockDashboard: DashboardType<QueryBasedInsightModel> = {
        id: 1,
        name: 'Test Dashboard',
        description: 'Test dashboard description',
        tiles: [
            {
                id: 1,
                insight: mockInsight as QueryBasedInsightModel,
            },
        ],
    } as DashboardType<QueryBasedInsightModel>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        logic = maxContextLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('core functionality', () => {
        it('manages current page context', async () => {
            await expectLogic(logic).toMatchValues({
                useCurrentPageContext: false,
            })

            await expectLogic(logic, () => {
                logic.actions.enableCurrentPageContext()
            }).toMatchValues({
                useCurrentPageContext: true,
            })

            await expectLogic(logic, () => {
                logic.actions.disableCurrentPageContext()
            }).toMatchValues({
                useCurrentPageContext: false,
            })
        })

        it('manages context data', async () => {
            await expectLogic(logic).toMatchValues({
                contextInsights: {},
                contextDashboards: {},
            })

            logic.actions.addOrUpdateContextInsight('test-key', mockInsight)
            logic.actions.addOrUpdateContextDashboard('1', mockDashboard)

            await expectLogic(logic).toMatchValues({
                contextInsights: { 'test-key': mockInsight },
                contextDashboards: { '1': mockDashboard },
            })
        })

        it('manages active insights', async () => {
            await expectLogic(logic).toMatchValues({
                activeInsights: {},
            })

            logic.actions.addOrUpdateActiveInsight('active-1', mockInsight)

            await expectLogic(logic).toMatchValues({
                activeInsights: { 'active-1': mockInsight },
            })

            logic.actions.clearActiveInsights()

            await expectLogic(logic).toMatchValues({
                activeInsights: {},
            })
        })

        it('manages active dashboard', async () => {
            await expectLogic(logic).toMatchValues({
                activeDashboard: null,
            })

            logic.actions.setActiveDashboard(mockDashboard)

            await expectLogic(logic).toMatchValues({
                activeDashboard: mockDashboard,
            })

            logic.actions.clearActiveDashboard()

            await expectLogic(logic).toMatchValues({
                activeDashboard: null,
            })
        })

        it('resets all context', async () => {
            logic.actions.addOrUpdateContextInsight('test', mockInsight)
            logic.actions.addOrUpdateContextDashboard('1', mockDashboard)
            logic.actions.enableCurrentPageContext()

            await expectLogic(logic).toMatchValues({
                contextInsights: { test: mockInsight },
                contextDashboards: { '1': mockDashboard },
                useCurrentPageContext: true,
            })

            logic.actions.resetContext()

            await expectLogic(logic).toMatchValues({
                contextInsights: {},
                contextDashboards: {},
                useCurrentPageContext: false,
            })
        })
    })

    describe('selectors', () => {
        it('calculates hasData correctly', async () => {
            await expectLogic(logic).toMatchValues({
                hasData: false,
            })

            logic.actions.addOrUpdateContextInsight('test', mockInsight)

            await expectLogic(logic).toMatchValues({
                hasData: true,
            })

            logic.actions.removeContextInsight('test')
            logic.actions.addOrUpdateActiveInsight('active', mockInsight)
            logic.actions.enableCurrentPageContext()

            await expectLogic(logic).toMatchValues({
                hasData: true,
            })
        })

        it('calculates contextOptions correctly', async () => {
            await expectLogic(logic).toMatchValues({
                contextOptions: [],
            })

            logic.actions.addOrUpdateActiveInsight('active', mockInsight)
            logic.actions.enableCurrentPageContext()

            await expectLogic(logic).toMatchValues({
                contextOptions: [
                    {
                        name: 'Current page',
                        value: 'current_page',
                        icon: IconPageChart,
                        items: {
                            insights: [mockInsight],
                            dashboards: [],
                        },
                    },
                ],
            })

            logic.actions.setActiveDashboard(mockDashboard)

            await expectLogic(logic).toMatchValues({
                contextOptions: [
                    {
                        name: 'Current page',
                        value: 'current_page',
                        icon: IconPageChart,
                        items: {
                            insights: [mockInsight],
                            dashboards: [mockDashboard],
                        },
                    },
                ],
            })
        })

        it('calculates taxonomic group types correctly', async () => {
            await expectLogic(logic).toMatchValues({
                mainTaxonomicGroupType: TaxonomicFilterGroupType.Insights,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Insights, TaxonomicFilterGroupType.Dashboards],
            })

            logic.actions.addOrUpdateActiveInsight('active', mockInsight)
            logic.actions.enableCurrentPageContext()

            await expectLogic(logic).toMatchValues({
                mainTaxonomicGroupType: TaxonomicFilterGroupType.MaxAIContext,
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.MaxAIContext,
                    TaxonomicFilterGroupType.Insights,
                    TaxonomicFilterGroupType.Dashboards,
                ],
            })
        })

        it('calculates dashboardInsightIds correctly', async () => {
            await expectLogic(logic).toMatchValues({
                dashboardInsightIds: new Set(),
            })

            logic.actions.addOrUpdateContextDashboard('1', mockDashboard)

            await expectLogic(logic).toMatchValues({
                dashboardInsightIds: new Set(['insight-1']),
            })

            const mockDashboard2 = {
                ...mockDashboard,
                id: 2,
                tiles: [
                    {
                        id: 2,
                        insight: { ...mockInsight, short_id: 'insight-2' } as QueryBasedInsightModel,
                    },
                ],
            } as DashboardType<QueryBasedInsightModel>

            logic.actions.setActiveDashboard(mockDashboard2)
            logic.actions.enableCurrentPageContext()

            await expectLogic(logic).toMatchValues({
                dashboardInsightIds: new Set(['insight-1', 'insight-2']),
            })
        })

        it('compiles context correctly', async () => {
            // Use different insight for context vs dashboard to avoid filtering
            const contextInsight = {
                ...mockInsight,
                short_id: 'context-insight-1' as any,
            }

            logic.actions.addOrUpdateContextInsight('insight-key', contextInsight)
            logic.actions.addOrUpdateContextDashboard('1', mockDashboard)
            logic.actions.setNavigationContext('/test', 'Test Page')

            await expectLogic(logic).toMatchValues({
                compiledContext: partial({
                    insights: {
                        'insight-key': {
                            id: 'context-insight-1',
                            name: 'Test Insight',
                            description: 'Test insight description',
                            query: { kind: 'TrendsQuery' },
                            insight_type: 'TrendsQuery',
                        },
                    },
                    dashboards: {
                        '1': {
                            id: 1,
                            name: 'Test Dashboard',
                            description: 'Test dashboard description',
                            insights: [
                                {
                                    id: 'insight-1',
                                    name: 'Test Insight',
                                    description: 'Test insight description',
                                    query: { kind: 'TrendsQuery' },
                                    insight_type: 'TrendsQuery',
                                },
                            ],
                        },
                    },
                    global_info: {
                        navigation: {
                            path: '/test',
                            page_title: 'Test Page',
                        },
                    },
                }),
            })
        })

        it('filters out insights already in dashboards from compiled context', async () => {
            logic.actions.addOrUpdateContextInsight('insight-1', mockInsight)
            logic.actions.addOrUpdateContextDashboard('1', mockDashboard)

            await expectLogic(logic).toMatchValues({
                compiledContext: partial({
                    dashboards: {
                        '1': partial({
                            insights: [partial({ id: 'insight-1' })],
                        }),
                    },
                }),
            })

            expect(logic.values.compiledContext?.insights).toBeUndefined()
        })

        it('includes active insights and dashboard when current page context is enabled', async () => {
            logic.actions.addOrUpdateActiveInsight('active-insight', mockInsight)
            logic.actions.setActiveDashboard(mockDashboard)
            logic.actions.enableCurrentPageContext()

            await expectLogic(logic).toMatchValues({
                compiledContext: partial({
                    dashboards: {
                        '1': partial({
                            id: 1,
                            insights: [partial({ id: 'insight-1' })],
                        }),
                    },
                }),
            })

            expect(logic.values.compiledContext?.insights).toBeUndefined()
        })
    })

    describe('listeners', () => {
        it('clears active data on location change', async () => {
            logic.actions.addOrUpdateActiveInsight('active', mockInsight)
            logic.actions.setActiveDashboard(mockDashboard)

            await expectLogic(logic).toMatchValues({
                activeInsights: { active: mockInsight },
                activeDashboard: mockDashboard,
            })

            await expectLogic(logic, () => {
                router.actions.push('/new-path')
            }).toMatchValues({
                activeInsights: {},
                activeDashboard: null,
            })
        })

        it('handles taxonomic filter change for current page context', async () => {
            await expectLogic(logic).toMatchValues({
                useCurrentPageContext: false,
            })

            await expectLogic(logic, () => {
                logic.actions.handleTaxonomicFilterChange(
                    'current_page',
                    TaxonomicFilterGroupType.MaxAIContext,
                    'current_page'
                )
            }).toMatchValues({
                useCurrentPageContext: true,
            })
        })
    })
})
