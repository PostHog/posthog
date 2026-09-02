import '@testing-library/jest-dom'

import { fireEvent, render } from '@testing-library/react'
import { useActions, useAsyncActions, useValues } from 'kea'
import { router } from 'kea-router'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { DashboardMode, DashboardPlacement } from '~/types'

import { DashboardItems } from './DashboardItems'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
    useAsyncActions: jest.fn(),
}))

jest.mock('scenes/dashboard/dashboardLogic', () => ({
    dashboardLogic: { __mock: 'dashboardLogic' },
    DashboardLoadAction: { Update: 'update' },
}))

jest.mock('~/models/dashboardsModel', () => ({
    dashboardsModel: { __mock: 'dashboardsModel' },
}))

jest.mock('~/models/insightsModel', () => ({
    insightsModel: { __mock: 'insightsModel' },
}))

jest.mock('lib/utils/eventUsageLogic', () => ({
    eventUsageLogic: { __mock: 'eventUsageLogic' },
    DashboardEventSource: {
        CardEdgeHover: 'CardEdgeHover',
        CardDragHandle: 'CardDragHandle',
    },
}))

jest.mock('kea-router', () => ({
    ...jest.requireActual('kea-router'),
    router: { __mock: 'router' },
}))

jest.mock('lib/hooks/useResizeObserver', () => ({
    useResizeObserver: () => ({ width: 1200, ref: { current: null } }),
}))

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => true,
}))

jest.mock('scenes/surveys/hooks/useSurveyLinkedInsights', () => ({
    useSurveyLinkedInsights: () => ({ data: [], loading: false }),
}))

jest.mock('scenes/surveys/utils/opportunityDetection', () => ({
    getBestSurveyOpportunityFunnel: () => null,
}))

jest.mock('scenes/insights/EmptyStates', () => ({
    InsightErrorState: ({ title, onRetry }: { title: string; onRetry?: () => void }) => (
        <div data-attr="insight-error-state" data-has-retry={onRetry ? 'true' : undefined}>
            {title}
            {onRetry && <button onClick={onRetry}>Retry error tile</button>}
        </div>
    ),
}))

jest.mock('~/exporter/exporterViewLogic', () => ({
    getCurrentExporterData: () => null,
    isSharedView: () => false,
}))

jest.mock('scenes/urls', () => ({
    ...jest.requireActual('scenes/urls'),
    urls: {
        ...jest.requireActual('scenes/urls').urls,
        dashboardTextTile: () => '/dashboard/5/text/1',
    },
}))

jest.mock('lib/components/Cards/InsightCard', () => ({
    InsightCard: (props: {
        tile: { id: number }
        showResizeHandles: boolean
        apiErrored?: boolean
        queryId?: string
        apiError?: Error & {
            status?: number
            detail?: string | null
            code?: string | null
            data?: { queryId?: string }
        }
        refresh?: () => void
    }): JSX.Element => {
        mockInsightCard(props)
        const { tile, showResizeHandles, apiErrored, apiError } = props
        return (
            <div
                data-attr="insight-card"
                data-tile-id={String(tile.id)}
                data-show-resize-handles={String(showResizeHandles)}
                data-api-errored={apiErrored ? 'true' : undefined}
                data-api-error-status={apiError?.status}
                data-api-error-detail={apiError?.detail ?? undefined}
                data-api-error-code={apiError?.code ?? undefined}
            />
        )
    },
}))

jest.mock('./items/DashboardTextItem', () => ({
    DashboardTextItem: ({ tile, showResizeHandles }: { tile: { id: number }; showResizeHandles: boolean }) => (
        <div
            data-attr="text-card"
            data-tile-id={String(tile.id)}
            data-show-resize-handles={String(showResizeHandles)}
        />
    ),
}))

jest.mock('react-grid-layout', () => {
    return {
        cloneLayoutItem: (item: Record<string, unknown>) => ({ ...item }),
        useContainerWidth: () => ({
            width: 1200,
            containerRef: { current: null },
            mounted: true,
        }),
        verticalCompactor: {
            type: 'vertical',
            allowOverlap: false,
            compact: (layout: unknown[]) => layout,
        },
        Responsive: ({
            className,
            rowHeight,
            margin,
            resizeConfig,
            dragConfig,
            children,
        }: {
            className: string
            rowHeight: number
            margin: [number, number]
            resizeConfig: { enabled: boolean }
            dragConfig: { enabled: boolean }
            children: any
        }) => (
            <div
                data-attr="react-grid-layout"
                data-class-name={className}
                data-row-height={String(rowHeight)}
                data-margin={margin.join(',')}
                data-resize-enabled={String(resizeConfig.enabled)}
                data-drag-enabled={String(dragConfig.enabled)}
            >
                {children}
            </div>
        ),
    }
})

jest.mock('react-grid-layout/extras', () => ({
    GridBackground: ({ rowHeight, margin }: { rowHeight: number; margin: [number, number] }) => (
        <div data-attr="grid-background" data-row-height={String(rowHeight)} data-margin={margin.join(',')} />
    ),
}))

jest.mock('@posthog/products-dashboards/frontend/components/DashboardWidgetItem/DashboardWidgetItem', () => ({
    DashboardWidgetItem: () => <div data-attr="widget-card" />,
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock
const mockedUseAsyncActions = useAsyncActions as jest.Mock
const mockRemoveTile = jest.fn()
const mockTriggerDashboardRefresh = jest.fn()
const mockInsightCard = jest.fn()

describe('DashboardItems', () => {
    beforeEach(() => {
        mockInsightCard.mockClear()
        jest.clearAllMocks()

        mockedUseValues.mockImplementation((logic) => {
            if (logic === dashboardLogic) {
                return {
                    dashboard: { id: 5 },
                    tiles: [
                        {
                            id: 1,
                            insight: { id: 101, short_id: 'abc123', query: { kind: 'InsightVizNode' } },
                        },
                    ],
                    layouts: {
                        sm: [{ i: '1', x: 0, y: 0, w: 6, h: 5 }],
                    },
                    dashboardMode: DashboardMode.Edit,
                    layoutEditMode: true,
                    placement: DashboardPlacement.Dashboard,
                    isRefreshingQueued: () => false,
                    isRefreshing: () => false,
                    highlightedInsightId: null,
                    refreshStatus: {},
                    itemsLoading: false,
                    dashboardStreaming: false,
                    effectiveEditBarFilters: {},
                    effectiveDashboardVariableOverrides: {},
                    temporaryBreakdownColors: [],
                    dataColorThemeId: null,
                    canEditDashboard: true,
                    layoutZoom: 0.75,
                }
            }

            if (logic === dashboardsModel) {
                return {
                    nameSortedDashboards: [{ id: 6, name: 'Other dashboard' }],
                }
            }

            return {}
        })

        mockedUseActions.mockImplementation((logic) => {
            if (logic === dashboardLogic) {
                return {
                    updateLayouts: jest.fn(),
                    updateContainerWidth: jest.fn(),
                    updateTileColor: jest.fn(),
                    toggleTileDescription: jest.fn(),
                    removeTile: mockRemoveTile,
                    duplicateTile: jest.fn(),
                    refreshDashboardItem: jest.fn(),
                    loadDashboard: mockTriggerDashboardRefresh,
                    refreshDashboardWidgets: jest.fn(),
                    moveToDashboard: jest.fn(),
                    copyToDashboard: jest.fn(),
                    setTileOverride: jest.fn(),
                    setDashboardMode: jest.fn(),
                }
            }

            if (logic === insightsModel) {
                return {
                    renameInsight: jest.fn(),
                }
            }

            if (logic === eventUsageLogic) {
                return {
                    reportDashboardTileRepositioned: jest.fn(),
                }
            }

            if (logic === router) {
                return {
                    push: jest.fn(),
                }
            }

            return {}
        })

        mockedUseAsyncActions.mockImplementation((logic) => {
            if (logic === dashboardLogic) {
                return {
                    updateWidgetTile: jest.fn(),
                }
            }

            return {}
        })
    })

    it('matches snapshot in edit mode with layout zoom enabled', () => {
        const { container } = render(<DashboardItems />)
        expect(container.firstChild).toMatchSnapshot()
    })

    it.each([
        ['tight', '8,8'],
        ['condensed', '12,12'],
        ['relaxed', '32,32'],
    ] as const)('uses %s tile spacing for tiles and the edit grid', (tileSpacing, margin) => {
        mockedUseValues.mockImplementation((logic) => {
            if (logic === dashboardLogic) {
                return {
                    dashboard: { id: 5, customization: { tile_spacing: tileSpacing } },
                    tiles: [],
                    layouts: { sm: [] },
                    dashboardMode: DashboardMode.Edit,
                    layoutEditMode: true,
                    placement: DashboardPlacement.Dashboard,
                    isRefreshingQueued: () => false,
                    isRefreshing: () => false,
                    highlightedInsightId: null,
                    refreshStatus: {},
                    dashboardStreaming: false,
                    effectiveEditBarFilters: {},
                    effectiveDashboardVariableOverrides: {},
                    dataColorThemeId: null,
                    canEditDashboard: true,
                    layoutZoom: 1,
                    widgetResultsByTileId: {},
                    widgetRefreshStatus: {},
                }
            }
            if (logic === dashboardsModel) {
                return { nameSortedDashboards: [] }
            }
            return {}
        })

        const { container } = render(<DashboardItems />)
        expect(container.querySelector('[data-attr="grid-background"]')).toHaveAttribute('data-margin', margin)
        expect(container.querySelector('[data-attr="react-grid-layout"]')).toHaveAttribute('data-margin', margin)
    })

    it('uses standard spacing when persisted customization is invalid', () => {
        mockedUseValues.mockImplementation((logic) => {
            if (logic === dashboardLogic) {
                return {
                    dashboard: { id: 5, customization: { tile_spacing: 'unknown' } },
                    tiles: [],
                    layouts: { sm: [] },
                    dashboardMode: DashboardMode.Edit,
                    layoutEditMode: true,
                    placement: DashboardPlacement.Dashboard,
                    isRefreshingQueued: () => false,
                    isRefreshing: () => false,
                    highlightedInsightId: null,
                    refreshStatus: {},
                    dashboardStreaming: false,
                    effectiveEditBarFilters: {},
                    effectiveDashboardVariableOverrides: {},
                    dataColorThemeId: null,
                    canEditDashboard: true,
                    layoutZoom: 1,
                    widgetResultsByTileId: {},
                    widgetRefreshStatus: {},
                }
            }
            if (logic === dashboardsModel) {
                return { nameSortedDashboards: [] }
            }
            return {}
        })

        const { container } = render(<DashboardItems />)
        expect(container.querySelector('[data-attr="react-grid-layout"]')).toHaveAttribute('data-margin', '16,16')
    })

    it('shows widget tiles on public dashboards', () => {
        const widgetTile = {
            id: 2,
            widget: { id: 1, widget_type: 'error_tracking_list', config: {} },
            layouts: { sm: [{ i: '2', x: 0, y: 0, w: 6, h: 5 }] },
        }

        mockedUseValues.mockImplementation((logic) => {
            if (logic === dashboardLogic) {
                return {
                    dashboard: { id: 5 },
                    tiles: [widgetTile],
                    layouts: widgetTile.layouts,
                    dashboardMode: null,
                    placement: DashboardPlacement.Public,
                    isRefreshingQueued: () => false,
                    isRefreshing: () => false,
                    highlightedInsightId: null,
                    refreshStatus: {},
                    itemsLoading: false,
                    dashboardStreaming: false,
                    effectiveEditBarFilters: {},
                    effectiveDashboardVariableOverrides: {},
                    temporaryBreakdownColors: [],
                    dataColorThemeId: null,
                    canEditDashboard: false,
                    layoutZoom: 1,
                    dashboardWidgetsEnabled: true,
                    widgetResultsByTileId: {},
                    widgetRefreshStatus: {},
                }
            }

            if (logic === dashboardsModel) {
                return { nameSortedDashboards: [] }
            }

            return {}
        })

        const { getByTestId } = render(<DashboardItems />)
        expect(getByTestId('widget-card')).toBeInTheDocument()
    })

    it('shows an actionable error card when a streamed tile fails before its insight is serialized', async () => {
        const errorTile = { id: 2, error: { type: 'ValidationError', message: 'Invalid filters' } }
        mockedUseValues.mockImplementation((logic) => {
            if (logic === dashboardLogic) {
                return {
                    dashboard: { id: 5 },
                    tiles: [errorTile],
                    layouts: { sm: [{ i: '2', x: 0, y: 0, w: 6, h: 5 }] },
                    dashboardMode: null,
                    placement: DashboardPlacement.Dashboard,
                    isRefreshingQueued: () => false,
                    isRefreshing: () => false,
                    highlightedInsightId: null,
                    refreshStatus: {},
                    dashboardStreaming: false,
                    effectiveEditBarFilters: {},
                    effectiveDashboardVariableOverrides: {},
                    temporaryBreakdownColors: [],
                    dataColorThemeId: null,
                    canEditDashboard: true,
                    layoutZoom: 1,
                    dashboardWidgetsEnabled: true,
                    widgetResultsByTileId: {},
                    widgetRefreshStatus: {},
                }
            }

            if (logic === dashboardsModel) {
                return { nameSortedDashboards: [] }
            }

            return {}
        })

        const { findByText, getByTestId, getByText } = render(<DashboardItems />)
        expect(getByText('Tile')).toBeInTheDocument()
        expect(getByText('There is a problem loading this dashboard tile.')).toHaveAttribute('data-has-retry', 'true')

        fireEvent.click(getByText('Retry error tile'))
        expect(mockTriggerDashboardRefresh).toHaveBeenCalled()

        fireEvent.click(getByTestId('more-button'))
        fireEvent.click(await findByText('Remove from dashboard'))
        expect(mockRemoveTile).toHaveBeenCalledWith(errorTile)
    })

    it('treats a streamed tile error with insight metadata as a server failure', () => {
        const errorTile = {
            id: 2,
            insight: { id: 101, short_id: 'abc123', query: { kind: 'InsightVizNode' } },
            error: {
                type: 'DashboardTileError',
                message: 'There is a problem loading this dashboard tile.',
            },
        }
        mockedUseValues.mockImplementation((logic) => {
            if (logic === dashboardLogic) {
                return {
                    dashboard: { id: 5 },
                    tiles: [errorTile],
                    layouts: { sm: [{ i: '2', x: 0, y: 0, w: 6, h: 5 }] },
                    dashboardMode: null,
                    placement: DashboardPlacement.Dashboard,
                    isRefreshingQueued: () => false,
                    isRefreshing: () => false,
                    highlightedInsightId: null,
                    refreshStatus: {},
                    dashboardStreaming: false,
                    effectiveEditBarFilters: {},
                    effectiveDashboardVariableOverrides: {},
                    temporaryBreakdownColors: [],
                    dataColorThemeId: null,
                    canEditDashboard: true,
                    layoutZoom: 1,
                    dashboardWidgetsEnabled: true,
                    widgetResultsByTileId: {},
                    widgetRefreshStatus: {},
                }
            }

            if (logic === dashboardsModel) {
                return { nameSortedDashboards: [] }
            }

            return {}
        })

        const { container } = render(<DashboardItems />)
        const insightCard = container.querySelector('[data-attr="insight-card"]')

        expect(insightCard).toHaveAttribute('data-api-errored', 'true')
        expect(insightCard).toHaveAttribute('data-api-error-status', '500')
        expect(insightCard).toHaveAttribute('data-api-error-code', 'dashboard_tile_error')
        expect(insightCard).toHaveAttribute('data-api-error-detail', 'There is a problem loading this dashboard tile.')
    })

    it('shows a query status error from an initially serialized insight', () => {
        const errorTile = {
            id: 2,
            insight: {
                id: 101,
                short_id: 'abc123',
                query: { kind: 'InsightVizNode' },
                query_status: {
                    id: 'failed-query-id',
                    error: true,
                    error_message: 'This query ran out of memory before it could finish',
                    error_code: 'query_memory_limit',
                },
            },
        }
        const refreshStatus = {}
        mockedUseValues.mockImplementation((logic) => {
            if (logic === dashboardLogic) {
                return {
                    dashboard: { id: 5 },
                    tiles: [errorTile],
                    layouts: { sm: [{ i: '2', x: 0, y: 0, w: 6, h: 5 }] },
                    dashboardMode: null,
                    placement: DashboardPlacement.Dashboard,
                    isRefreshingQueued: () => false,
                    isRefreshing: () => false,
                    highlightedInsightId: null,
                    refreshStatus,
                    dashboardStreaming: false,
                    effectiveEditBarFilters: {},
                    effectiveDashboardVariableOverrides: {},
                    temporaryBreakdownColors: [],
                    dataColorThemeId: null,
                    canEditDashboard: true,
                    layoutZoom: 1,
                    dashboardWidgetsEnabled: true,
                    widgetResultsByTileId: {},
                    widgetRefreshStatus: {},
                }
            }

            if (logic === dashboardsModel) {
                return { nameSortedDashboards: [] }
            }

            return {}
        })

        const { container, rerender } = render(<DashboardItems />)
        const insightCard = container.querySelector('[data-attr="insight-card"]')

        expect(insightCard).toHaveAttribute('data-api-errored', 'true')
        expect(insightCard).toHaveAttribute('data-api-error-status', '400')
        expect(insightCard).toHaveAttribute('data-api-error-code', 'query_memory_limit')
        expect(mockInsightCard).toHaveBeenCalledWith(
            expect.objectContaining({
                refresh: expect.any(Function),
                queryId: 'failed-query-id',
            })
        )
        expect(insightCard).toHaveAttribute(
            'data-api-error-detail',
            'This query ran out of memory before it could finish'
        )

        Object.assign(refreshStatus, {
            abc123: {
                errored: true,
                error: {
                    status: 503,
                    detail: 'The refreshed query failed',
                    code: 'refresh_failed',
                },
            },
        })
        rerender(<DashboardItems />)

        expect(insightCard).toHaveAttribute('data-api-error-status', '503')
        expect(insightCard).toHaveAttribute('data-api-error-code', 'refresh_failed')
        expect(insightCard).toHaveAttribute('data-api-error-detail', 'The refreshed query failed')
    })
})
