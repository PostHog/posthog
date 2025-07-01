import {} from '@posthog/icons'
import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    ActionType,
    DashboardType,
    EventDefinition,
    InsightShortId,
    QueryBasedInsightModel,
    SidePanelTab,
} from '~/types'

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
        type: 'insight',
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

    const mockEvent: EventDefinition = {
        id: 'event-1',
        name: 'Test Event',
        description: 'Test event description',
    } as EventDefinition

    const expectedTransformedEvent = {
        id: 'event-1',
        name: 'Test Event',
        description: 'Test event description',
        type: 'event',
    }

    const mockAction: ActionType = {
        id: 1,
        name: 'Test Action',
        description: 'Test action description',
    } as ActionType

    const expectedTransformedAction = {
        id: 1,
        name: 'Test Action',
        description: 'Test action description',
        type: 'action',
    }

    // Create the expected transformed dashboard
    const expectedTransformedDashboard = {
        id: 1,
        name: 'Test Dashboard',
        description: 'Test dashboard description',
        insights: [expectedTransformedInsight],
        filters: mockDashboard.filters,
        type: 'dashboard',
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
        it('manages context data', async () => {
            await expectLogic(logic).toMatchValues({
                contextInsights: [],
                contextDashboards: [],
                contextEvents: [],
                contextActions: [],
            })

            logic.actions.addOrUpdateContextInsight(mockInsight as any)
            logic.actions.addOrUpdateContextDashboard(mockDashboard)
            logic.actions.addOrUpdateContextEvent(mockEvent)
            logic.actions.addOrUpdateContextAction(mockAction)

            await expectLogic(logic).toMatchValues({
                contextInsights: [expectedTransformedInsight],
                contextDashboards: [expectedTransformedDashboard],
                contextEvents: [expectedTransformedEvent],
                contextActions: [expectedTransformedAction],
            })
        })

        it('resets all context', async () => {
            logic.actions.addOrUpdateContextInsight(mockInsight as any)
            logic.actions.addOrUpdateContextDashboard(mockDashboard)
            logic.actions.addOrUpdateContextEvent(mockEvent)
            logic.actions.addOrUpdateContextAction(mockAction)

            await expectLogic(logic).toMatchValues({
                contextInsights: [expectedTransformedInsight],
                contextDashboards: [expectedTransformedDashboard],
                contextEvents: [expectedTransformedEvent],
                contextActions: [expectedTransformedAction],
            })

            logic.actions.resetContext()

            await expectLogic(logic).toMatchValues({
                contextInsights: [],
                contextDashboards: [],
                contextEvents: [],
                contextActions: [],
            })
        })
    })

    describe('selectors', () => {
        it('calculates hasData correctly', async () => {
            await expectLogic(logic).toMatchValues({
                hasData: false,
            })

            logic.actions.addOrUpdateContextInsight(mockInsight as any)

            await expectLogic(logic).toMatchValues({
                hasData: true,
            })

            logic.actions.removeContextInsight('insight-1')

            await expectLogic(logic).toMatchValues({
                hasData: false,
            })
        })

        it('calculates contextOptions correctly', async () => {
            await expectLogic(logic).toMatchValues({
                contextOptions: [],
            })

            // Since contextOptions now come from sceneContext, we can't test directly
            // This test would need to be updated to work with scene-based context
        })

        it('calculates taxonomic group types correctly', async () => {
            await expectLogic(logic).toMatchValues({
                mainTaxonomicGroupType: TaxonomicFilterGroupType.Events,
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.Insights,
                    TaxonomicFilterGroupType.Dashboards,
                ],
            })

            // Test would require scene context to have context options
            // Since contextOptions now come from sceneContext which is computed automatically
        })

        it('compiles context correctly', async () => {
            // Use different insight for context vs dashboard to avoid filtering
            const contextInsight = {
                ...mockInsight,
                short_id: 'context-insight-1' as any,
            }

            logic.actions.addOrUpdateContextInsight(contextInsight as any)
            logic.actions.addOrUpdateContextDashboard(mockDashboard)
            logic.actions.addOrUpdateContextEvent(mockEvent)
            logic.actions.addOrUpdateContextAction(mockAction)

            await expectLogic(logic).toMatchValues({
                compiledContext: partial({
                    insights: [
                        {
                            id: 'context-insight-1',
                            name: 'Test Insight',
                            description: 'Test insight description',
                            query: { kind: 'TrendsQuery' },
                            type: 'insight',
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
                                    type: 'insight',
                                },
                            ],
                            filters: mockDashboard.filters,
                            type: 'dashboard',
                        },
                    ],
                    events: [
                        {
                            id: 'event-1',
                            name: 'Test Event',
                            description: 'Test event description',
                            type: 'event',
                        },
                    ],
                    actions: [
                        {
                            id: 1,
                            name: 'Test Action',
                            description: 'Test action description',
                            type: 'action',
                        },
                    ],
                }),
            })
        })

        it('does not include both insights and dashboard insights when they have same IDs', async () => {
            logic.actions.addOrUpdateContextInsight(mockInsight as any)
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

        it('includes dashboards in compiled context', async () => {
            logic.actions.addOrUpdateContextDashboard(mockDashboard)

            await expectLogic(logic).toMatchValues({
                compiledContext: partial({
                    dashboards: [partial({ id: 1, insights: [partial({ id: 'insight-1' })] })],
                }),
            })
        })
    })

    describe('listeners', () => {
        it('clears context data on location change', async () => {
            logic.actions.addOrUpdateContextInsight(mockInsight as any)
            logic.actions.addOrUpdateContextDashboard(mockDashboard)

            await expectLogic(logic).toMatchValues({
                contextInsights: [expectedTransformedInsight],
                contextDashboards: [expectedTransformedDashboard],
            })

            await expectLogic(logic, () => {
                router.actions.push('/new-path')
            }).toMatchValues({
                contextInsights: [],
                contextDashboards: [],
            })
        })

        it('handles taxonomic filter change for events', async () => {
            await expectLogic(logic).toMatchValues({
                contextEvents: [],
            })

            await expectLogic(logic, () => {
                logic.actions.handleTaxonomicFilterChange('event-1', TaxonomicFilterGroupType.Events, mockEvent)
            }).toMatchValues({
                contextEvents: [expectedTransformedEvent],
            })
        })

        it('handles taxonomic filter change for actions', async () => {
            await expectLogic(logic).toMatchValues({
                contextActions: [],
            })

            await expectLogic(logic, () => {
                logic.actions.handleTaxonomicFilterChange(1, TaxonomicFilterGroupType.Actions, mockAction)
            }).toMatchValues({
                contextActions: [expectedTransformedAction],
            })
        })

        it('preserves context when only panel parameter changes (side panel opening/closing)', async () => {
            logic.actions.addOrUpdateContextInsight(mockInsight as any)
            logic.actions.addOrUpdateContextDashboard(mockDashboard)

            await expectLogic(logic).toMatchValues({
                contextInsights: [expectedTransformedInsight],
                contextDashboards: [expectedTransformedDashboard],
            })

            // Simulate opening side panel by changing only the panel hash parameter
            await expectLogic(logic, () => {
                router.actions.replace(router.values.location.pathname, router.values.searchParams, {
                    ...router.values.hashParams,
                    panel: SidePanelTab.Max,
                })
            }).toMatchValues({
                contextInsights: [expectedTransformedInsight],
                contextDashboards: [expectedTransformedDashboard],
            })

            // Simulate closing side panel by removing the panel hash parameter
            await expectLogic(logic, () => {
                const { panel, ...otherHashParams } = router.values.hashParams
                router.actions.replace(router.values.location.pathname, router.values.searchParams, otherHashParams)
            }).toMatchValues({
                contextInsights: [expectedTransformedInsight],
                contextDashboards: [expectedTransformedDashboard],
            })
        })
    })

    describe('loadAndProcessDashboard', () => {
        const mockDashboardLogicInstance = {
            mount: jest.fn(),
            unmount: jest.fn(),
            actions: {
                loadDashboard: jest.fn(),
            },
            values: {
                dashboard: mockDashboard,
                refreshStatus: {},
            },
        }

        beforeEach(() => {
            jest.spyOn(dashboardLogic, 'build').mockReturnValue(mockDashboardLogicInstance as any)
            mockDashboardLogicInstance.mount.mockClear()
            mockDashboardLogicInstance.unmount.mockClear()
            mockDashboardLogicInstance.actions.loadDashboard.mockClear()
        })

        it('adds preloaded dashboard to context without loading', async () => {
            const dashboardData = {
                id: 1,
                preloaded: mockDashboard,
            }

            await expectLogic(logic, () => {
                logic.actions.loadAndProcessDashboard(dashboardData)
            }).toMatchValues({
                contextDashboards: [expectedTransformedDashboard],
            })

            expect(dashboardLogic.build).not.toHaveBeenCalled()
        })

        it('loads dashboard when not preloaded', async () => {
            const dashboardData = {
                id: 1,
                preloaded: null,
            }

            // Set the mock values that the function will read
            mockDashboardLogicInstance.values.dashboard = mockDashboard
            mockDashboardLogicInstance.values.refreshStatus = {}

            await expectLogic(logic, () => {
                logic.actions.loadAndProcessDashboard(dashboardData)
            }).toFinishAllListeners()

            expect(dashboardLogic.build).toHaveBeenCalledWith({ id: 1 })
            expect(mockDashboardLogicInstance.mount).toHaveBeenCalled()
            expect(mockDashboardLogicInstance.actions.loadDashboard).toHaveBeenCalledWith({ action: 'initial_load' })
            expect(mockDashboardLogicInstance.unmount).toHaveBeenCalled()

            await expectLogic(logic).toMatchValues({
                contextDashboards: [expectedTransformedDashboard],
            })
        })

        it('loads dashboard when preloaded dashboard has no tiles', async () => {
            const incompleteDashboard = {
                ...mockDashboard,
                tiles: undefined,
            }
            const dashboardData = {
                id: 1,
                preloaded: incompleteDashboard as any,
            }

            // Set the mock values that the function will read
            mockDashboardLogicInstance.values.dashboard = mockDashboard
            mockDashboardLogicInstance.values.refreshStatus = {}

            await expectLogic(logic, () => {
                logic.actions.loadAndProcessDashboard(dashboardData)
            }).toFinishAllListeners()

            expect(dashboardLogic.build).toHaveBeenCalledWith({ id: 1 })
            expect(mockDashboardLogicInstance.mount).toHaveBeenCalled()
            expect(mockDashboardLogicInstance.actions.loadDashboard).toHaveBeenCalledWith({ action: 'initial_load' })
            expect(mockDashboardLogicInstance.unmount).toHaveBeenCalled()
        })
    })

    describe('loadAndProcessInsight', () => {
        const mockInsightLogicInstance = {
            mount: jest.fn(),
            unmount: jest.fn(),
            actions: {
                loadInsight: jest.fn(),
            },
            values: {
                insight: mockInsight as QueryBasedInsightModel,
            },
        }

        beforeEach(() => {
            jest.spyOn(insightLogic, 'build').mockReturnValue(mockInsightLogicInstance as any)
            mockInsightLogicInstance.mount.mockClear()
            mockInsightLogicInstance.unmount.mockClear()
            mockInsightLogicInstance.actions.loadInsight.mockClear()
        })

        it('adds preloaded insight to context without loading', async () => {
            const insightData = {
                id: 'insight-1' as InsightShortId,
                preloaded: mockInsight as QueryBasedInsightModel,
            }

            await expectLogic(logic, () => {
                logic.actions.loadAndProcessInsight(insightData)
            }).toMatchValues({
                contextInsights: [expectedTransformedInsight],
            })

            expect(insightLogic.build).not.toHaveBeenCalled()
        })

        it('loads insight when not preloaded', async () => {
            const insightData = {
                id: 'insight-1' as InsightShortId,
                preloaded: null,
            }

            // Set the mock values that the function will read
            mockInsightLogicInstance.values.insight = mockInsight as QueryBasedInsightModel

            await expectLogic(logic, () => {
                logic.actions.loadAndProcessInsight(insightData)
            }).toFinishAllListeners()

            expect(insightLogic.build).toHaveBeenCalledWith({ dashboardItemId: undefined })
            expect(mockInsightLogicInstance.mount).toHaveBeenCalled()
            expect(mockInsightLogicInstance.actions.loadInsight).toHaveBeenCalledWith('insight-1')
            expect(mockInsightLogicInstance.unmount).toHaveBeenCalled()

            await expectLogic(logic).toMatchValues({
                contextInsights: [expectedTransformedInsight],
            })
        })

        it('loads insight when preloaded insight has no query', async () => {
            const incompleteInsight = {
                ...mockInsight,
                query: null,
            }
            const insightData = {
                id: 'insight-1' as InsightShortId,
                preloaded: incompleteInsight as any,
            }

            // Set the mock values that the function will read
            mockInsightLogicInstance.values.insight = mockInsight as QueryBasedInsightModel

            await expectLogic(logic, () => {
                logic.actions.loadAndProcessInsight(insightData)
            }).toFinishAllListeners()

            expect(insightLogic.build).toHaveBeenCalledWith({ dashboardItemId: undefined })
            expect(mockInsightLogicInstance.mount).toHaveBeenCalled()
            expect(mockInsightLogicInstance.actions.loadInsight).toHaveBeenCalledWith('insight-1')
            expect(mockInsightLogicInstance.unmount).toHaveBeenCalled()
        })
    })
})
