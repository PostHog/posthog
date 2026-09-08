import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { useActions, useAsyncActions, useValues } from 'kea'
import { router } from 'kea-router'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { urls } from 'scenes/urls'

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
        dashboardTile: () => '/dashboard/5/tiles/1/text',
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
        highlighted?: boolean
        'data-dashboard-tile-id'?: string
        'data-dashboard-tile-highlighted'?: string
        tabIndex?: number
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
                data-dashboard-tile-id={props['data-dashboard-tile-id']}
                data-dashboard-tile-highlighted={props['data-dashboard-tile-highlighted']}
                tabIndex={props.tabIndex}
            />
        )
    },
}))

jest.mock('products/dashboards/frontend/components/DashboardTextItem/DashboardTextItem', () => ({
    DashboardTextItem: ({
        tile,
        showResizeHandles,
        'data-dashboard-tile-id': dashboardTileId,
        'data-dashboard-tile-highlighted': dashboardTileHighlighted,
        tabIndex,
    }: {
        tile: { id: number }
        showResizeHandles: boolean
        'data-dashboard-tile-id'?: string
        'data-dashboard-tile-highlighted'?: string
        tabIndex?: number
    }) => (
        <div
            data-attr="text-card"
            data-tile-id={String(tile.id)}
            data-show-resize-handles={String(showResizeHandles)}
            data-dashboard-tile-id={dashboardTileId}
            data-dashboard-tile-highlighted={dashboardTileHighlighted}
            tabIndex={tabIndex}
        />
    ),
}))

jest.mock('./items/DashboardButtonTileItem', () => ({
    DashboardButtonTileItem: ({
        tile,
        'data-dashboard-tile-id': dashboardTileId,
        'data-dashboard-tile-highlighted': dashboardTileHighlighted,
        tabIndex,
    }: {
        tile: { id: number }
        'data-dashboard-tile-id'?: string
        'data-dashboard-tile-highlighted'?: string
        tabIndex?: number
    }) => (
        <div
            data-attr="button-tile-card"
            data-tile-id={String(tile.id)}
            data-dashboard-tile-id={dashboardTileId}
            data-dashboard-tile-highlighted={dashboardTileHighlighted}
            tabIndex={tabIndex}
        />
    ),
}))

jest.mock('react-grid-layout', () => {
    const containerRef = { current: null }

    return {
        cloneLayoutItem: (item: Record<string, unknown>) => ({ ...item }),
        useContainerWidth: () => ({
            width: 1200,
            containerRef,
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
    DashboardWidgetItem: (props: {
        tile: { id: number }
        'data-dashboard-tile-id'?: string
        'data-dashboard-tile-highlighted'?: string
        tabIndex?: number
    }) => (
        <div
            data-attr="widget-card"
            data-tile-id={String(props.tile.id)}
            data-dashboard-tile-id={props['data-dashboard-tile-id']}
            data-dashboard-tile-highlighted={props['data-dashboard-tile-highlighted']}
            tabIndex={props.tabIndex}
        />
    ),
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock
const mockedUseAsyncActions = useAsyncActions as jest.Mock
const mockRemoveTile = jest.fn()
const mockTriggerDashboardRefresh = jest.fn()
const mockInsightCard = jest.fn()
const requestAnimationFrameCallbacks = new Map<number, FrameRequestCallback>()
let requestAnimationFrameId = 0
let mockHighlightedInsightId: string | null = null
let mockHasHighlightTileIdParam = false
let mockHighlightTileIdParam: unknown
let mockHighlightedTileId: number | null = null
let mockDashboardLoading = false
let mockDashboardRevealReadyKey: string | null = null

type DashboardTileFixture = {
    id: number
    insight?: { id: number; short_id: string; query: { kind: string } }
    text?: { id: number; body: string }
    button_tile?: { id: number; text: string; url: string; style: 'primary' }
    widget?: { id: number; widget_type: string; config: Record<string, never> }
    error?: { type: string; message: string }
}

function installDashboardValues(getTiles: () => DashboardTileFixture[]): void {
    mockedUseValues.mockImplementation((logic) => {
        if (logic === dashboardLogic) {
            const tiles = getTiles()
            return {
                dashboard: { id: 5 },
                tiles,
                layouts: {
                    sm: tiles.map((tile, index) => ({ i: String(tile.id), x: index * 2, y: 0, w: 2, h: 5 })),
                },
                dashboardMode: DashboardMode.Edit,
                layoutEditMode: true,
                placement: DashboardPlacement.Dashboard,
                isRefreshingQueued: () => false,
                isRefreshing: () => false,
                highlightedInsightId: mockHighlightedInsightId,
                hasHighlightTileIdParam: mockHasHighlightTileIdParam,
                highlightTileIdParam: mockHighlightTileIdParam,
                highlightedTileId: mockHighlightedTileId,
                refreshStatus: {},
                dashboardStreaming: false,
                dashboardLoading: mockDashboardLoading,
                dashboardRevealReadyKey: mockDashboardRevealReadyKey,
                effectiveEditBarFilters: {},
                effectiveDashboardVariableOverrides: {},
                effectiveBreakdownColors: [],
                dataColorThemeId: null,
                canEditDashboard: true,
                dashboardWidgetsEnabled: true,
                widgetResultsByTileId: {},
                widgetRefreshStatus: {},
                scrollToBottomSignal: 0,
                layoutZoom: 1,
            }
        }

        if (logic === dashboardsModel) {
            return { nameSortedDashboards: [] }
        }

        return {}
    })
}

function flushNextAnimationFrame(): number {
    const entry = requestAnimationFrameCallbacks.entries().next().value as [number, FrameRequestCallback] | undefined
    if (!entry) {
        throw new Error('No animation frame is scheduled')
    }
    const [id, callback] = entry
    requestAnimationFrameCallbacks.delete(id)
    callback(0)
    return id
}

function flushAllAnimationFrames(): void {
    while (requestAnimationFrameCallbacks.size > 0) {
        flushNextAnimationFrame()
    }
}

function installAnimationFrameMocks(): void {
    global.requestAnimationFrame = jest.fn((callback: FrameRequestCallback): number => {
        const id = ++requestAnimationFrameId
        requestAnimationFrameCallbacks.set(id, callback)
        return id
    })
    global.cancelAnimationFrame = jest.fn((id: number): void => {
        requestAnimationFrameCallbacks.delete(id)
    })
}

describe('DashboardItems', () => {
    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    beforeEach(() => {
        mockInsightCard.mockClear()
        jest.clearAllMocks()
        requestAnimationFrameCallbacks.clear()
        requestAnimationFrameId = 0
        mockHighlightedInsightId = null
        mockHasHighlightTileIdParam = false
        mockHighlightTileIdParam = undefined
        mockHighlightedTileId = null
        mockDashboardLoading = false
        mockDashboardRevealReadyKey = null
        installAnimationFrameMocks()
        Object.defineProperty(window, 'matchMedia', {
            configurable: true,
            value: jest.fn().mockReturnValue({ matches: false }),
        })

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
                    highlightedInsightId: mockHighlightedInsightId,
                    hasHighlightTileIdParam: mockHasHighlightTileIdParam,
                    highlightTileIdParam: mockHighlightTileIdParam,
                    highlightedTileId: mockHighlightedTileId,
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

    it('builds an explicit dashboard tile reveal URL', () => {
        expect(urls.dashboard(7, undefined, 41)).toBe('/dashboard/7?highlightTileId=41')
    })

    it.each([42, '42'])('prefers an explicit tile target of %p over the legacy insight target', (rawTarget) => {
        const tiles: DashboardTileFixture[] = [
            { id: 41, insight: { id: 101, short_id: 'legacy-target', query: { kind: 'InsightVizNode' } } },
            { id: 42, text: { id: 102, body: 'Explicit target' } },
        ]
        mockHighlightedInsightId = 'legacy-target'
        mockHasHighlightTileIdParam = true
        mockHighlightTileIdParam = rawTarget
        mockHighlightedTileId = 42
        mockDashboardRevealReadyKey = '5:tile:42'
        installDashboardValues(() => tiles)

        const { container } = render(<DashboardItems />)
        const legacyTarget = container.querySelector('[data-tile-id="41"]') as HTMLElement
        const explicitTarget = container.querySelector('[data-tile-id="42"]') as HTMLElement
        legacyTarget.scrollIntoView = jest.fn()
        explicitTarget.scrollIntoView = jest.fn()
        explicitTarget.focus = jest.fn()

        act(flushAllAnimationFrames)

        expect(legacyTarget.scrollIntoView).not.toHaveBeenCalled()
        expect(explicitTarget.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' })
        expect(explicitTarget.focus).toHaveBeenCalledWith({ preventScroll: true })
    })

    it.each(['invalid', '0', '-1', '1.5', String(Number.MAX_SAFE_INTEGER + 1)])(
        'does not fall back to an insight when the explicit tile target is %s',
        (rawTarget) => {
            const tiles: DashboardTileFixture[] = [
                { id: 41, insight: { id: 101, short_id: 'legacy-target', query: { kind: 'InsightVizNode' } } },
            ]
            mockHighlightedInsightId = 'legacy-target'
            mockHasHighlightTileIdParam = true
            mockHighlightTileIdParam = rawTarget
            mockHighlightedTileId = null
            installDashboardValues(() => tiles)

            const { container } = render(<DashboardItems />)
            const legacyTarget = container.querySelector('[data-tile-id="41"]') as HTMLElement
            legacyTarget.scrollIntoView = jest.fn()
            legacyTarget.focus = jest.fn()

            act(flushAllAnimationFrames)

            expect(legacyTarget.scrollIntoView).not.toHaveBeenCalled()
            expect(legacyTarget.focus).not.toHaveBeenCalled()
        }
    )

    it('uses the legacy insight target only when the tile parameter is absent', () => {
        const tiles: DashboardTileFixture[] = [
            { id: 41, insight: { id: 101, short_id: 'legacy-target', query: { kind: 'InsightVizNode' } } },
        ]
        mockHighlightedInsightId = 'legacy-target'
        mockDashboardRevealReadyKey = '5:insight:legacy-target'
        installDashboardValues(() => tiles)

        const { container } = render(<DashboardItems />)
        const target = container.querySelector('[data-tile-id="41"]') as HTMLElement
        target.scrollIntoView = jest.fn()
        target.focus = jest.fn()

        act(flushAllAnimationFrames)

        expect(target.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' })
        expect(target.focus).toHaveBeenCalledWith({ preventScroll: true })
    })

    it('reveals a requested tile after it arrives in dashboard state', () => {
        const tile: DashboardTileFixture = {
            id: 42,
            insight: { id: 101, short_id: 'tile-target', query: { kind: 'InsightVizNode' } },
        }
        let tiles: DashboardTileFixture[] = []
        mockHasHighlightTileIdParam = true
        mockHighlightTileIdParam = '42'
        mockHighlightedTileId = 42
        mockDashboardRevealReadyKey = '5:tile:42'
        installDashboardValues(() => tiles)

        const { container, rerender } = render(<DashboardItems />)
        expect(requestAnimationFrameCallbacks.size).toBe(0)

        tiles = [tile]
        rerender(<DashboardItems />)
        const target = container.querySelector('[data-tile-id="42"]') as HTMLElement
        target.scrollIntoView = jest.fn()
        target.focus = jest.fn()
        act(flushAllAnimationFrames)

        expect(target.scrollIntoView).toHaveBeenCalledTimes(1)
        expect(target.focus).toHaveBeenCalledTimes(1)
    })

    it('waits for the dashboard refresh before revealing an existing tile', () => {
        let tiles: DashboardTileFixture[] = [
            { id: 41, insight: { id: 101, short_id: 'before-update', query: { kind: 'InsightVizNode' } } },
        ]
        installDashboardValues(() => tiles)

        const { container, rerender } = render(<DashboardItems />)
        const staleTarget = container.querySelector('[data-tile-id="41"]') as HTMLElement
        staleTarget.scrollIntoView = jest.fn()
        staleTarget.focus = jest.fn()

        mockHasHighlightTileIdParam = true
        mockHighlightTileIdParam = '41'
        mockHighlightedTileId = 41
        rerender(<DashboardItems />)

        act(flushAllAnimationFrames)
        expect(staleTarget.scrollIntoView).not.toHaveBeenCalled()
        expect(staleTarget.focus).not.toHaveBeenCalled()

        tiles = [{ id: 41, insight: { id: 101, short_id: 'after-update', query: { kind: 'InsightVizNode' } } }]
        mockDashboardRevealReadyKey = '5:tile:41'
        rerender(<DashboardItems />)

        const refreshedTarget = container.querySelector('[data-tile-id="41"]') as HTMLElement
        refreshedTarget.scrollIntoView = jest.fn()
        refreshedTarget.focus = jest.fn()
        act(flushAllAnimationFrames)
        rerender(<DashboardItems />)

        expect(refreshedTarget.scrollIntoView).toHaveBeenCalledTimes(1)
        expect(refreshedTarget.focus).toHaveBeenCalledTimes(1)
    })

    it('cancels a stale reveal between animation frames when the target changes', () => {
        const tiles: DashboardTileFixture[] = [
            { id: 41, insight: { id: 101, short_id: 'first', query: { kind: 'InsightVizNode' } } },
            { id: 42, insight: { id: 102, short_id: 'second', query: { kind: 'InsightVizNode' } } },
        ]
        mockHasHighlightTileIdParam = true
        mockHighlightTileIdParam = '41'
        mockHighlightedTileId = 41
        mockDashboardRevealReadyKey = '5:tile:41'
        installDashboardValues(() => tiles)

        const { container, rerender } = render(<DashboardItems />)
        const firstTarget = container.querySelector('[data-tile-id="41"]') as HTMLElement
        const secondTarget = container.querySelector('[data-tile-id="42"]') as HTMLElement
        firstTarget.scrollIntoView = jest.fn()
        firstTarget.focus = jest.fn()
        secondTarget.scrollIntoView = jest.fn()
        secondTarget.focus = jest.fn()
        const firstFrameId = flushNextAnimationFrame()
        const secondFrameId = requestAnimationFrameId

        mockHighlightTileIdParam = '42'
        mockHighlightedTileId = 42
        mockDashboardRevealReadyKey = '5:tile:42'
        rerender(<DashboardItems />)

        expect(firstTarget.scrollIntoView).not.toHaveBeenCalled()
        expect(secondTarget.scrollIntoView).not.toHaveBeenCalled()
        act(flushAllAnimationFrames)

        expect(cancelAnimationFrame).toHaveBeenCalledWith(firstFrameId)
        expect(cancelAnimationFrame).toHaveBeenCalledWith(secondFrameId)
        expect(firstTarget.scrollIntoView).not.toHaveBeenCalled()
        expect(firstTarget.focus).not.toHaveBeenCalled()
        expect(secondTarget.scrollIntoView).toHaveBeenCalledTimes(1)
        expect(secondTarget.focus).toHaveBeenCalledTimes(1)
    })

    it('does not reveal for an invalid explicit tile target', () => {
        const tiles: DashboardTileFixture[] = [
            { id: 41, insight: { id: 101, short_id: 'legacy-target', query: { kind: 'InsightVizNode' } } },
        ]
        installDashboardValues(() => tiles)

        const { rerender } = render(<DashboardItems />)
        mockHasHighlightTileIdParam = true
        mockHighlightTileIdParam = 'invalid'
        mockHighlightedTileId = null
        mockHighlightedInsightId = 'legacy-target'
        rerender(<DashboardItems />)

        expect(requestAnimationFrameCallbacks.size).toBe(0)
    })

    it('cancels both reveal frames when the dashboard unmounts', () => {
        const tiles: DashboardTileFixture[] = [
            { id: 41, insight: { id: 101, short_id: 'target', query: { kind: 'InsightVizNode' } } },
        ]
        mockHasHighlightTileIdParam = true
        mockHighlightTileIdParam = '41'
        mockHighlightedTileId = 41
        mockDashboardRevealReadyKey = '5:tile:41'
        installDashboardValues(() => tiles)

        const { container, unmount } = render(<DashboardItems />)
        const target = container.querySelector('[data-tile-id="41"]') as HTMLElement
        target.scrollIntoView = jest.fn()
        target.focus = jest.fn()
        const firstFrameId = flushNextAnimationFrame()
        const secondFrameId = requestAnimationFrameId

        unmount()
        act(flushAllAnimationFrames)

        expect(cancelAnimationFrame).toHaveBeenCalledWith(firstFrameId)
        expect(cancelAnimationFrame).toHaveBeenCalledWith(secondFrameId)
        expect(target.scrollIntoView).not.toHaveBeenCalled()
        expect(target.focus).not.toHaveBeenCalled()
    })

    it('does not reveal a consumed target again after dashboard tiles reload', () => {
        let tiles: DashboardTileFixture[] = [
            { id: 41, insight: { id: 101, short_id: 'target', query: { kind: 'InsightVizNode' } } },
        ]
        mockHasHighlightTileIdParam = true
        mockHighlightTileIdParam = '41'
        mockHighlightedTileId = 41
        mockDashboardRevealReadyKey = '5:tile:41'
        installDashboardValues(() => tiles)

        const { container, rerender } = render(<DashboardItems />)
        const target = container.querySelector('[data-tile-id="41"]') as HTMLElement
        target.scrollIntoView = jest.fn()
        target.focus = jest.fn()
        act(flushAllAnimationFrames)

        tiles = []
        rerender(<DashboardItems />)
        tiles = [{ id: 41, insight: { id: 101, short_id: 'target', query: { kind: 'InsightVizNode' } } }]
        rerender(<DashboardItems />)
        expect(requestAnimationFrameCallbacks.size).toBe(0)
        act(flushAllAnimationFrames)

        expect(target.scrollIntoView).toHaveBeenCalledTimes(1)
        expect(target.focus).toHaveBeenCalledTimes(1)
    })

    it('uses non-animated scrolling when reduced motion is requested', () => {
        const tiles: DashboardTileFixture[] = [
            { id: 41, insight: { id: 101, short_id: 'target', query: { kind: 'InsightVizNode' } } },
        ]
        mockHasHighlightTileIdParam = true
        mockHighlightTileIdParam = '41'
        mockHighlightedTileId = 41
        mockDashboardRevealReadyKey = '5:tile:41'
        installDashboardValues(() => tiles)
        jest.mocked(window.matchMedia).mockReturnValue({ matches: true } as MediaQueryList)

        const { container } = render(<DashboardItems />)
        const target = container.querySelector('[data-tile-id="41"]') as HTMLElement
        target.scrollIntoView = jest.fn()
        target.focus = jest.fn()
        act(flushAllAnimationFrames)

        expect(target.scrollIntoView).toHaveBeenCalledWith({ behavior: 'auto', block: 'center' })
    })

    it.each([
        ['insight', { id: 41, insight: { id: 101, short_id: 'target', query: { kind: 'InsightVizNode' } } }],
        ['text', { id: 41, text: { id: 102, body: 'Text' } }],
        ['image', { id: 41, text: { id: 102, body: '![Image](https://example.test/image.png)' } }],
        ['button', { id: 41, button_tile: { id: 103, text: 'Open', url: '/', style: 'primary' } }],
        ['widget', { id: 41, widget: { id: 104, widget_type: 'error_tracking_list', config: {} } }],
        ['error', { id: 41, error: { type: 'ValidationError', message: 'Invalid filters' } }],
    ] as const)('applies the common focus and visual contract to a highlighted %s tile', (_kind, tile) => {
        jest.useFakeTimers()
        installAnimationFrameMocks()
        mockHasHighlightTileIdParam = true
        mockHighlightTileIdParam = '41'
        mockHighlightedTileId = 41
        mockDashboardRevealReadyKey = '5:tile:41'
        installDashboardValues(() => [tile])

        const { container } = render(<DashboardItems />)
        const target = container.querySelector('[data-tile-id="41"], [data-attr="dashboard-tile-error"]') as HTMLElement
        target.scrollIntoView = jest.fn()
        target.focus = jest.fn()
        act(flushAllAnimationFrames)

        expect(target).toHaveAttribute('data-dashboard-tile-id', '41')
        expect(target).toHaveAttribute('tabindex', '-1')
        expect(target).toHaveAttribute('data-dashboard-tile-highlighted', 'true')

        act(() => jest.advanceTimersByTime(2999))
        expect(target).toHaveAttribute('data-dashboard-tile-highlighted', 'true')
        act(() => jest.advanceTimersByTime(1))
        expect(target).not.toHaveAttribute('data-dashboard-tile-highlighted')
    })

    it('keeps the visual highlight for 3000ms when reduced motion is requested', () => {
        jest.useFakeTimers()
        installAnimationFrameMocks()
        mockHasHighlightTileIdParam = true
        mockHighlightTileIdParam = '41'
        mockHighlightedTileId = 41
        mockDashboardRevealReadyKey = '5:tile:41'
        installDashboardValues(() => [
            { id: 41, insight: { id: 101, short_id: 'target', query: { kind: 'InsightVizNode' } } },
        ])
        jest.mocked(window.matchMedia).mockReturnValue({ matches: true } as MediaQueryList)

        const { container } = render(<DashboardItems />)
        const target = container.querySelector('[data-tile-id="41"]') as HTMLElement
        target.scrollIntoView = jest.fn()
        target.focus = jest.fn()
        act(flushAllAnimationFrames)

        act(() => jest.advanceTimersByTime(2999))
        expect(target).toHaveAttribute('data-dashboard-tile-highlighted', 'true')
        act(() => jest.advanceTimersByTime(1))
        expect(target).not.toHaveAttribute('data-dashboard-tile-highlighted')
    })

    it('expires the legacy insight card highlight after 3000ms', () => {
        jest.useFakeTimers()
        installAnimationFrameMocks()
        mockHighlightedInsightId = 'target'
        mockDashboardRevealReadyKey = '5:insight:target'
        installDashboardValues(() => [
            { id: 41, insight: { id: 101, short_id: 'target', query: { kind: 'InsightVizNode' } } },
        ])

        render(<DashboardItems />)
        act(flushAllAnimationFrames)

        expect(mockInsightCard).toHaveBeenLastCalledWith(expect.objectContaining({ highlighted: true }))
        act(() => jest.advanceTimersByTime(3000))
        expect(mockInsightCard).toHaveBeenLastCalledWith(expect.objectContaining({ highlighted: false }))
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
