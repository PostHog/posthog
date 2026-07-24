import '@testing-library/jest-dom'

import { act, fireEvent, render } from '@testing-library/react'
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
    InsightErrorState: ({ title, supportOnly }: { title: string; supportOnly?: boolean }) => (
        <div data-attr="insight-error-state" data-support-only={supportOnly ? 'true' : undefined}>
            {title}
        </div>
    ),
}))

jest.mock('~/exporter/exporterViewLogic', () => ({
    getCurrentExporterData: () => null,
}))

jest.mock('scenes/urls', () => ({
    ...jest.requireActual('scenes/urls'),
    urls: {
        ...jest.requireActual('scenes/urls').urls,
        dashboardTextTile: () => '/dashboard/5/text/1',
    },
}))

jest.mock('lib/components/Cards/InsightCard', () => ({
    InsightCard: ({
        tile,
        showResizeHandles,
        apiErrored,
        apiError,
    }: {
        tile: { id: number }
        showResizeHandles: boolean
        apiErrored?: boolean
        apiError?: Error & { status?: number; detail?: string | null; code?: string | null }
    }) => (
        <div
            data-attr="insight-card"
            data-tile-id={String(tile.id)}
            data-show-resize-handles={String(showResizeHandles)}
            data-api-errored={apiErrored ? 'true' : undefined}
            data-api-error-status={apiError?.status}
            data-api-error-detail={apiError?.detail ?? undefined}
            data-api-error-code={apiError?.code ?? undefined}
        />
    ),
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

// Mutable so individual tests can simulate the container reporting a different (or transient zero) width.
const mockContainerWidth = { width: 1200, containerRef: { current: null }, mounted: true }

jest.mock('react-grid-layout', () => {
    return {
        useContainerWidth: () => mockContainerWidth,
        Responsive: ({
            width,
            className,
            rowHeight,
            margin,
            resizeConfig,
            dragConfig,
            children,
        }: {
            width: number
            className: string
            rowHeight: number
            margin: [number, number]
            resizeConfig: { enabled: boolean }
            dragConfig: { enabled: boolean }
            children: any
        }) => (
            <div
                data-attr="react-grid-layout"
                data-width={String(width)}
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

describe('DashboardItems', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        mockContainerWidth.width = 1200
        mockContainerWidth.mounted = true

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
        expect(getByText('There is a problem loading this dashboard tile.')).toHaveAttribute(
            'data-support-only',
            'true'
        )

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

    it('keeps the last good width when the container reports a transient zero measurement', () => {
        jest.useFakeTimers()
        try {
            const { container, rerender } = render(<DashboardItems />)
            expect(container.querySelector('[data-attr="react-grid-layout"]')).toHaveAttribute('data-width', '1200')

            // A container measured before it has laid out reports width 0, which maps to the xs (1-column)
            // breakpoint. The grid must ignore it and keep its last good width rather than squash every tile.
            mockContainerWidth.width = 0
            // Two acts: the first flushes the effect (which reschedules the debounce timer for the new width),
            // the second fires it. Doing both in one act would advance timers before the effect re-runs.
            act(() => {
                rerender(<DashboardItems />)
            })
            act(() => {
                jest.advanceTimersByTime(200)
            })

            expect(container.querySelector('[data-attr="react-grid-layout"]')).toHaveAttribute('data-width', '1200')
        } finally {
            jest.useRealTimers()
        }
    })
})
