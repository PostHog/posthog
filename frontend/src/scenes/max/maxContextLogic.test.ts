import { IconDashboard, IconGraph, IconPageChart } from '@posthog/icons'
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

    // Create the expected transformed insight
    const expectedTransformedInsight = {
        id: 'insight-1',
        name: 'Test Insight',
        description: 'Test insight description',
        query: { kind: 'TrendsQuery' },
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

    // Create the expected transformed dashboard
    const expectedTransformedDashboard = {
        id: 1,
        name: 'Test Dashboard',
        description: 'Test dashboard description',
        insights: [expectedTransformedInsight],
        filters: mockDashboard.filters,
    }

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
                contextInsights: [],
                contextDashboards: [],
            })

            logic.actions.addOrUpdateContextInsight(mockInsight)
            logic.actions.addOrUpdateContextDashboard(mockDashboard)

            await expectLogic(logic).toMatchValues({
                contextInsights: [expectedTransformedInsight],
                contextDashboards: [expectedTransformedDashboard],
            })
        })

        it('manages active insights', async () => {
            await expectLogic(logic).toMatchValues({
                activeInsights: [],
            })

            logic.actions.addOrUpdateActiveInsight(mockInsight, false)

            await expectLogic(logic).toMatchValues({
                activeInsights: [expectedTransformedInsight],
            })

            logic.actions.clearActiveInsights()

            await expectLogic(logic).toMatchValues({
                activeInsights: [],
            })
        })

        it('manages active dashboard', async () => {
            await expectLogic(logic).toMatchValues({
                activeDashboard: null,
            })

            logic.actions.setActiveDashboard(mockDashboard)

            await expectLogic(logic).toMatchValues({
                activeDashboard: expectedTransformedDashboard,
            })

            logic.actions.clearActiveDashboard()

            await expectLogic(logic).toMatchValues({
                activeDashboard: null,
            })
        })

        it('resets all context', async () => {
            logic.actions.addOrUpdateContextInsight(mockInsight)
            logic.actions.addOrUpdateContextDashboard(mockDashboard)
            logic.actions.enableCurrentPageContext()

            await expectLogic(logic).toMatchValues({
                contextInsights: [expectedTransformedInsight],
                contextDashboards: [expectedTransformedDashboard],
                useCurrentPageContext: true,
            })

            logic.actions.resetContext()

            await expectLogic(logic).toMatchValues({
                contextInsights: [],
                contextDashboards: [],
                useCurrentPageContext: false,
            })
        })
    })

    describe('selectors', () => {
        it('calculates hasData correctly', async () => {
            await expectLogic(logic).toMatchValues({
                hasData: false,
            })

            logic.actions.addOrUpdateContextInsight(mockInsight)

            await expectLogic(logic).toMatchValues({
                hasData: true,
            })

            logic.actions.removeContextInsight('test')
            logic.actions.addOrUpdateActiveInsight(mockInsight, false)
            logic.actions.enableCurrentPageContext()

            await expectLogic(logic).toMatchValues({
                hasData: true,
            })
        })

        it('calculates contextOptions correctly', async () => {
            await expectLogic(logic).toMatchValues({
                contextOptions: [],
            })

            logic.actions.addOrUpdateActiveInsight(mockInsight, false)
            logic.actions.enableCurrentPageContext()

            await expectLogic(logic).toMatchValues({
                contextOptions: [
                    {
                        id: 'current_page',
                        name: 'Current page',
                        value: 'current_page',
                        icon: IconPageChart,
                        items: {
                            insights: [expectedTransformedInsight],
                            dashboards: [],
                        },
                    },
                    {
                        id: 'insight-1',
                        name: 'Test Insight',
                        value: 'insight-1',
                        type: 'insight',
                        icon: IconGraph,
                    },
                ],
            })

            logic.actions.setActiveDashboard(mockDashboard)

            await expectLogic(logic).toMatchValues({
                contextOptions: [
                    {
                        id: 'current_page',
                        name: 'Current page',
                        value: 'current_page',
                        icon: IconPageChart,
                        items: {
                            insights: [expectedTransformedInsight],
                            dashboards: [expectedTransformedDashboard],
                        },
                    },
                    {
                        id: '1',
                        name: 'Test Dashboard',
                        value: 1,
                        type: 'dashboard',
                        icon: IconDashboard,
                    },
                    {
                        id: 'insight-1',
                        name: 'Test Insight',
                        value: 'insight-1',
                        type: 'insight',
                        icon: IconGraph,
                    },
                ],
            })
        })

        it('calculates taxonomic group types correctly', async () => {
            await expectLogic(logic).toMatchValues({
                mainTaxonomicGroupType: TaxonomicFilterGroupType.Insights,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Insights, TaxonomicFilterGroupType.Dashboards],
            })

            logic.actions.addOrUpdateActiveInsight(mockInsight, false)
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

        it('compiles context correctly', async () => {
            // Use different insight for context vs dashboard to avoid filtering
            const contextInsight = {
                ...mockInsight,
                short_id: 'context-insight-1' as any,
            }

            logic.actions.addOrUpdateContextInsight(contextInsight)
            logic.actions.addOrUpdateContextDashboard(mockDashboard)

            await expectLogic(logic).toMatchValues({
                compiledContext: partial({
                    insights: [
                        {
                            id: 'context-insight-1',
                            name: 'Test Insight',
                            description: 'Test insight description',
                            query: { kind: 'TrendsQuery' },
                        },
                    ],
                    dashboards: [
                        {
                            id: 1,
                            name: 'Test Dashboard',
                            description: 'Test dashboard description',
                            insights: [
                                {
                                    id: 'insight-1',
                                    name: 'Test Insight',
                                    description: 'Test insight description',
                                    query: { kind: 'TrendsQuery' },
                                },
                            ],
                        },
                    ],
                }),
            })
        })

        it('does not include both insights and dashboard insights when they have same IDs', async () => {
            logic.actions.addOrUpdateContextInsight(mockInsight)
            logic.actions.addOrUpdateContextDashboard(mockDashboard)

            await expectLogic(logic).toMatchValues({
                compiledContext: partial({
                    dashboards: [
                        partial({
                            insights: [partial({ id: 'insight-1' })],
                        }),
                    ],
                }),
            })
        })

        it('includes active dashboard when current page context is enabled without insights', async () => {
            logic.actions.addOrUpdateActiveInsight(mockInsight, false)
            logic.actions.setActiveDashboard(mockDashboard)
            logic.actions.enableCurrentPageContext()

            await expectLogic(logic).toMatchValues({
                compiledContext: partial({
                    dashboards: [partial({ id: 1, insights: [partial({ id: 'insight-1' })] })],
                }),
            })
        })
    })

    describe('listeners', () => {
        it('clears active data on location change', async () => {
            logic.actions.addOrUpdateActiveInsight(mockInsight, false)
            logic.actions.setActiveDashboard(mockDashboard)

            await expectLogic(logic).toMatchValues({
                activeInsights: [expectedTransformedInsight],
                activeDashboard: expectedTransformedDashboard,
            })

            await expectLogic(logic, () => {
                router.actions.push('/new-path')
            }).toMatchValues({
                activeInsights: [],
                activeDashboard: null,
            })
        })

        it('handles taxonomic filter change for current page context', async () => {
            await expectLogic(logic).toMatchValues({
                useCurrentPageContext: false,
            })

            await expectLogic(logic, () => {
                logic.actions.handleTaxonomicFilterChange('current_page', TaxonomicFilterGroupType.MaxAIContext, {
                    id: 'current_page',
                    name: 'Current page',
                    value: 'current_page',
                    icon: IconPageChart,
                })
            }).toMatchValues({
                useCurrentPageContext: true,
            })
        })
    })
})
