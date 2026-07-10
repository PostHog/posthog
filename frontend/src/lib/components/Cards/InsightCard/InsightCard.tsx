import './InsightCard.scss'

import { useMergeRefs } from '@floating-ui/react'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import React, { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { LayoutItem } from 'react-grid-layout'
import { useInView } from 'react-intersection-observer'

import { ApiError } from 'lib/api'
import { Resizeable } from 'lib/components/Cards/CardMeta'
import { FEATURE_FLAGS } from 'lib/constants'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { accessLevelSatisfied, getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { BreakdownColorConfig } from 'scenes/dashboard/DashboardInsightColorsModal'
import {
    InsightErrorState,
    InsightLoadingState,
    InsightTimeoutState,
    InsightValidationError,
} from 'scenes/insights/EmptyStates'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { extractValidationError, extractValidationErrorCode } from '~/queries/nodes/InsightViz/utils'
import { Query } from '~/queries/Query/Query'
import { DashboardFilter, HogQLVariable } from '~/queries/schema/schema-general'
import { queryVizRendersToCanvas } from '~/queries/utils'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DashboardBasicType,
    DashboardPlacement,
    DashboardTile,
    DashboardType,
    InsightColor,
    InsightLogicProps,
    InsightShortId,
    QueryBasedInsightModel,
} from '~/types'

import type { AlertType } from 'products/alerts/frontend/types'

import { DashboardResizeHandles } from '../handles'
import { EditModeEdge, EditModeEdgeOverlay } from './EditModeEdgeOverlay'
import { InsightMeta } from './InsightMeta'

const IS_STORYBOOK = inStorybook() || inStorybookTestRunner()

const LazyEditAlertModal = React.lazy(() =>
    import('products/alerts/frontend/views/EditAlertModal').then(({ EditAlertModal }) => ({ default: EditAlertModal }))
)

const RESIZE_REDRAW_THROTTLE_MS = 33 // ~30x/sec

/**
 * Throttles a canvas chart's redraws while its dashboard tile is resized, instead of repainting on every frame.
 * Pinning the inner wrapper to a fixed size means the chart's own ResizeObserver only fires when we push a new
 * size, which we do at most once per {@link RESIZE_REDRAW_THROTTLE_MS}. Unpinning on resize-stop redraws once
 * at the exact final size.
 */
function ResizeThrottledViz({ throttled, children }: { throttled: boolean; children: React.ReactNode }): JSX.Element {
    const outerRef = useRef<HTMLDivElement>(null)
    const innerRef = useRef<HTMLDivElement>(null)

    useLayoutEffect(() => {
        const outer = outerRef.current
        const inner = innerRef.current
        if (!throttled || !outer || !inner) {
            return
        }

        let lastPush = 0
        let trailing: ReturnType<typeof setTimeout> | undefined

        const pushSize = (): void => {
            lastPush = performance.now()
            const rect = outer.getBoundingClientRect()
            inner.style.width = `${rect.width}px`
            inner.style.height = `${rect.height}px`
        }
        pushSize()

        const onOuterResize = (): void => {
            const elapsed = performance.now() - lastPush
            if (elapsed >= RESIZE_REDRAW_THROTTLE_MS) {
                if (trailing) {
                    clearTimeout(trailing)
                    trailing = undefined
                }
                pushSize()
            } else if (!trailing) {
                trailing = setTimeout(() => {
                    trailing = undefined
                    pushSize()
                }, RESIZE_REDRAW_THROTTLE_MS - elapsed)
            }
        }
        const observer = new ResizeObserver(onOuterResize)
        observer.observe(outer)

        return () => {
            observer.disconnect()
            if (trailing) {
                clearTimeout(trailing)
            }
            inner.style.width = ''
            inner.style.height = ''
        }
    }, [throttled])

    return (
        <div ref={outerRef} className={clsx('InsightCard__viz', throttled && 'InsightCard__viz--resizing')}>
            <div ref={innerRef} className="InsightCard__vizInner">
                {children}
            </div>
        </div>
    )
}

type AlertModalState = {
    alertId?: AlertType['id']
    defaultToAnomalyDetection?: boolean
}

export interface InsightCardProps extends Resizeable {
    /** Insight to display. */
    insight: QueryBasedInsightModel
    /** id of the dashboard the card is on (when the card is being displayed on a dashboard) **/
    dashboardId?: DashboardType['id']
    /** Whether the insight has been called to load. */
    loadingQueued?: boolean
    /** Whether the insight is loading. */
    loading?: boolean
    /** Whether an error occurred on the server. */
    apiErrored?: boolean
    /** Might contain more information on the error that occurred on the server. */
    apiError?: Error
    /** Whether the card should be highlighted with a blue border. */
    highlighted?: boolean
    /** Whether loading timed out. */
    timedOut?: boolean
    /** Whether the editing controls should be enabled or not. */
    showEditingControls?: boolean
    /** While this tile is being resized: throttle canvas chart redraws instead of repainting on every frame. */
    isResizing?: boolean
    /** Whether the  controls for showing details should be enabled or not. */
    showDetailsControls?: boolean
    /** Layout of the card on a grid. */
    layout?: LayoutItem
    ribbonColor?: InsightColor | null
    updateColor?: (newColor: DashboardTile['color']) => void
    toggleShowDescription?: () => void
    removeFromDashboard?: () => void
    deleteWithUndo?: () => Promise<void>
    refresh?: () => void
    rename?: () => void
    duplicate?: () => void
    setOverride?: () => void
    moveToDashboard?: (target: Pick<DashboardType, 'id' | 'name'>) => void
    /** Copy this insight tile to another dashboard (same insight; requires editor on destination). */
    copyToDashboard?: (dashboard: DashboardBasicType) => void
    /** buttons to add to the "more" menu on the card**/
    moreButtons?: JSX.Element | null
    placement: DashboardPlacement | 'SavedInsightGrid'
    /** Priority for loading the insight, lower is earlier. */
    loadPriority?: number
    doNotLoad?: boolean
    /** Dashboard filters to override the ones in the insight */
    filtersOverride?: DashboardFilter
    /** Dashboard variables to override the ones in the insight */
    variablesOverride?: Record<string, HogQLVariable>
    /** Dashboard breakdown colors to override the ones in the insight */
    breakdownColorOverride?: BreakdownColorConfig[]
    /** Dashboard color theme to override the ones in the insight */
    dataColorThemeId?: number | null
    className?: string
    style?: React.CSSProperties
    children?: React.ReactNode
    tile?: DashboardTile<QueryBasedInsightModel>
    /** survey opportunity for this insight */
    surveyOpportunity?: boolean
    /** Show a direct action for creating an anomaly detection alert for this saved insight. */
    showCreateAnomalyAlertButton?: boolean
    /** Whether hovering near the card edge should hint that edit mode is available. */
    canEnterEditModeFromEdge?: boolean
    /** Called when the user clicks an edge hint to enter edit mode. */
    onEnterEditModeFromEdge?: (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge) => void
    /** Called when the user mousedowns on the card (drag handle) in view mode to enter edit mode. */
    onDragHandleMouseDown?: React.MouseEventHandler<HTMLDivElement>
}

function InsightCardInternal(
    {
        tile,
        insight,
        dashboardId,
        ribbonColor,
        loadingQueued,
        loading,
        apiError,
        apiErrored,
        timedOut,
        highlighted,
        showResizeHandles,
        isResizing,
        showEditingControls,
        showDetailsControls,
        updateColor,
        toggleShowDescription,
        removeFromDashboard,
        deleteWithUndo,
        refresh,
        rename,
        duplicate,
        setOverride,
        moveToDashboard,
        copyToDashboard,
        className,
        moreButtons,
        placement,
        loadPriority,
        doNotLoad,
        filtersOverride,
        variablesOverride,
        children,
        breakdownColorOverride: _breakdownColorOverride,
        dataColorThemeId: _dataColorThemeId,
        surveyOpportunity,
        showCreateAnomalyAlertButton,
        canEnterEditModeFromEdge,
        onEnterEditModeFromEdge,
        onDragHandleMouseDown,
        ...divProps
    }: InsightCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { ref: inViewRef, inView } = useInView({ rootMargin: '500px' })
    const { isVisible: isPageVisible } = usePageVisibility()

    /** Wether the page is active and the line graph is currently in view. Used to free resources, by not rendering
     * insight cards that aren't visible. See also https://wiki.whatwg.org/wiki/Canvas_Context_Loss_and_Restoration.
     *
     * We add an extra check to make sure all insights are visible in Storybook.
     */
    const isVisible =
        featureFlags[FEATURE_FLAGS.EXPERIMENTAL_DASHBOARD_ITEM_RENDERING] === false
            ? true
            : IS_STORYBOOK || placement === DashboardPlacement.Export || (inView && isPageVisible)

    const mergedRefs = useMergeRefs([ref, inViewRef])

    const { theme } = useValues(themeLogic)

    const canEditInsight = insight.user_access_level
        ? accessLevelSatisfied(AccessControlResourceType.Insight, insight.user_access_level, AccessControlLevel.Editor)
        : true
    const canPersistDisplayOptions = !!dashboardId && canEditInsight

    // Base props without setQuery — used to mount insightDataLogic and retrieve the
    // persistDisplayOptions action before wiring it back in as setQuery below.
    const insightLogicPropsBase: InsightLogicProps = useMemo(
        () => ({
            dashboardItemId: insight.short_id,
            dashboardId: dashboardId,
            cachedInsight: insight,
            loadPriority,
            doNotLoad,
        }),
        [insight, dashboardId, loadPriority, doNotLoad]
    )

    const { persistDisplayOptions } = useActions(insightDataLogic(insightLogicPropsBase))

    // Stable reference so the memoized viz below isn't invalidated on every grid re-render.
    const insightLogicProps: InsightLogicProps = useMemo(
        () => ({
            ...insightLogicPropsBase,
            setQuery: canPersistDisplayOptions ? persistDisplayOptions : undefined,
        }),
        [insightLogicPropsBase, canPersistDisplayOptions, persistDisplayOptions]
    )

    const { insightLoading } = useValues(insightLogic(insightLogicProps))
    const { insightDataLoading } = useValues(insightDataLogic(insightLogicProps))

    if (insightLoading || insightDataLoading) {
        loading = true
    }

    const [areDetailsShown, setAreDetailsShown] = useState(false)
    const [alertModal, setAlertModal] = useState<AlertModalState | null>(null)
    const openCreateAlertModal = useCallback(() => setAlertModal({}), [])
    const openEditAlertModal = useCallback((alertId: AlertType['id']) => setAlertModal({ alertId }), [])
    const openCreateAnomalyAlertModal = useCallback(() => setAlertModal({ defaultToAnomalyDetection: true }), [])
    const closeAlertModal = useCallback(() => setAlertModal(null), [])
    const hasResults = !!insight?.result || !!(insight as any)?.results

    // Empty states that completely replace the Query component.
    const BlockingEmptyState = (() => {
        // Check for access denied - use the same logic as other components
        const canViewInsight = insight?.user_access_level
            ? accessLevelSatisfied(
                  AccessControlResourceType.Insight,
                  insight.user_access_level,
                  AccessControlLevel.Viewer
              )
            : true

        if (!canViewInsight) {
            const errorMessage = getAccessControlDisabledReason(
                AccessControlResourceType.Insight,
                insight.user_access_level,
                AccessControlLevel.Viewer,
                false
            )

            return (
                <InsightErrorState
                    data-attr="insight-access-denied-state"
                    title={errorMessage || "You don't have permission to view this insight."}
                    excludeDetail
                />
            )
        }

        if (!hasResults && loadingQueued) {
            return <InsightLoadingState insightProps={insightLogicProps} />
        }

        if (apiErrored) {
            const validationError = extractValidationError(apiError)
            if (validationError) {
                return (
                    <InsightValidationError
                        detail={validationError}
                        validationErrorCode={extractValidationErrorCode(apiError)}
                    />
                )
            } else if (apiError instanceof ApiError) {
                return <InsightErrorState title={apiError?.detail} />
            }
            return <InsightErrorState />
        }

        if (timedOut) {
            return <InsightTimeoutState />
        }

        return null
    })()

    // Excludes isResizing from the deps so the element stays referentially stable across resize toggles — that's
    // what lets ResizeThrottledViz throttle the live chart instead of remounting (and reloading) it.
    const vizInner = useMemo(() => {
        if (BlockingEmptyState) {
            return BlockingEmptyState
        }
        return (
            <Query
                query={insight.query}
                cachedResults={insight}
                context={{
                    insightProps: insightLogicProps,
                }}
                readOnly
                embedded
                inSharedMode={placement === DashboardPlacement.Public}
                variablesOverride={variablesOverride}
                editMode={false}
            />
        )
    }, [BlockingEmptyState, insight, insightLogicProps, variablesOverride, placement])

    // Only canvas viz (charts) redraw per resize frame; tables/numbers/maps are cheap DOM/SVG and stay fully live.
    const vizContent = isVisible ? (
        <ResizeThrottledViz throttled={!!isResizing && queryVizRendersToCanvas(insight.query)}>
            {vizInner}
        </ResizeThrottledViz>
    ) : null

    return (
        <div
            className={clsx(
                'DashboardTileCard InsightCard border',
                highlighted && 'InsightCard--highlighted',
                areDetailsShown && 'InsightCard--details-shown',
                className
            )}
            data-attr="insight-card"
            {...divProps}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ ...divProps?.style, ...theme?.boxStyle }}
            ref={mergedRefs}
        >
            <ErrorBoundary exceptionProps={{ feature: 'insight' }}>
                <BindLogic logic={insightLogic} props={insightLogicProps}>
                    <InsightMeta
                        tile={tile}
                        insight={insight}
                        ribbonColor={ribbonColor}
                        dashboardId={dashboardId}
                        persistDisplayOptions={canPersistDisplayOptions ? persistDisplayOptions : undefined}
                        updateColor={updateColor}
                        toggleShowDescription={toggleShowDescription}
                        removeFromDashboard={removeFromDashboard}
                        deleteWithUndo={deleteWithUndo}
                        refresh={refresh}
                        loadingQueued={loadingQueued}
                        loading={loading}
                        rename={rename}
                        duplicate={duplicate}
                        setOverride={setOverride}
                        moveToDashboard={moveToDashboard}
                        copyToDashboard={copyToDashboard}
                        areDetailsShown={areDetailsShown}
                        setAreDetailsShown={setAreDetailsShown}
                        showEditingControls={showEditingControls}
                        showDetailsControls={showDetailsControls}
                        moreButtons={moreButtons}
                        filtersOverride={filtersOverride}
                        variablesOverride={variablesOverride}
                        placement={placement}
                        surveyOpportunity={surveyOpportunity}
                        showCreateAnomalyAlertButton={showCreateAnomalyAlertButton}
                        onCreateAlert={openCreateAlertModal}
                        onEditAlert={openEditAlertModal}
                        onCreateAnomalyAlert={openCreateAnomalyAlertModal}
                        onDragHandleMouseDown={onDragHandleMouseDown}
                    />
                    {vizContent}
                </BindLogic>
            </ErrorBoundary>
            {showResizeHandles && <DashboardResizeHandles />}
            {canEnterEditModeFromEdge && !showResizeHandles && onEnterEditModeFromEdge && (
                <EditModeEdgeOverlay onEnterEditMode={onEnterEditModeFromEdge} />
            )}
            {alertModal && insight.id && insight.short_id ? (
                <React.Suspense fallback={<SpinnerOverlay />}>
                    <LazyEditAlertModal
                        isOpen
                        onClose={closeAlertModal}
                        alertId={alertModal.alertId}
                        insightId={insight.id}
                        insightShortId={insight.short_id as InsightShortId}
                        onEditSuccess={closeAlertModal}
                        insightLogicProps={insightLogicProps}
                        defaultToAnomalyDetection={alertModal.defaultToAnomalyDetection}
                        insightName={insight.name || insight.derived_name}
                    />
                </React.Suspense>
            ) : null}
            {children /* RGL react-resizable-handle nodes injected by react-grid-layout */}
        </div>
    )
}

export const InsightCard = React.forwardRef(InsightCardInternal) as typeof InsightCardInternal
