import './InsightCard.scss'

import { useMergeRefs } from '@floating-ui/react'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { LayoutItem } from 'react-grid-layout'
import { useInView } from 'react-intersection-observer'

import { ApiError } from 'lib/api'
import { Resizeable } from 'lib/components/Cards/CardMeta'
import { useInterval } from 'lib/hooks/useInterval'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { themeLogic } from 'lib/logic/themeLogic'
import { accessLevelSatisfied, getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { BreakdownColorConfig } from 'scenes/dashboard/dashboardBreakdownColors'
import {
    InsightErrorState,
    InsightLoadingState,
    InsightTimeoutState,
    InsightValidationError,
} from 'scenes/insights/EmptyStates'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getCapacityRetryAt, getRetryCooldown } from 'scenes/insights/sharedUtils'

import { isSharedView } from '~/exporter/exporterViewLogic'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { extractValidationError, extractValidationErrorCode } from '~/queries/nodes/InsightViz/utils'
import { Query } from '~/queries/Query/Query'
import { DashboardFilter, HogQLVariable } from '~/queries/schema/schema-general'
import { queryVizDefinitelyRendersToCanvas } from '~/queries/utils'
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
    InsightModel,
} from '~/types'

import type { AlertType } from 'products/alerts/frontend/types'

import { DashboardResizeHandles } from '../handles'
import { EditModeEdge, EditModeEdgeOverlay } from './EditModeEdgeOverlay'
import { INSIGHT_CARD_KEY_ATTR, insightCardKey } from './insightCardImageCapture'
import { InsightMeta } from './InsightMeta'
import { InsightVisualizationSkeleton } from './InsightVisualizationSkeleton'

const IS_STORYBOOK = inStorybook() || inStorybookTestRunner()

export function shouldRenderInsightCardViz({
    isStorybook,
    placement,
    inView,
    isPageVisible,
    query,
}: {
    isStorybook: boolean
    placement: DashboardPlacement | 'SavedInsightGrid'
    inView: boolean
    isPageVisible: boolean
    query: InsightModel['query']
}): boolean {
    if (isStorybook || placement === DashboardPlacement.Export) {
        return true
    }

    if (!inView) {
        return false
    }

    return isPageVisible || !queryVizDefinitelyRendersToCanvas(query)
}

const LazyEditAlertModal = lazyWithRetry(() =>
    import('products/alerts/frontend/views/EditAlertModal').then(({ EditAlertModal }) => ({ default: EditAlertModal }))
)

type AlertModalState = {
    alertId?: AlertType['id']
    defaultToAnomalyDetection?: boolean
}

export interface InsightCardProps extends Resizeable {
    /** Insight to display. */
    insight: InsightModel
    /** id of the dashboard the card is on (when the card is being displayed on a dashboard) **/
    dashboardId?: DashboardType['id']
    canEditDashboard?: boolean
    /** Whether the insight has been called to load. */
    loadingQueued?: boolean
    /** Whether the insight is loading. */
    loading?: boolean
    /** Whether an error occurred on the server. */
    apiErrored?: boolean
    /** Might contain more information on the error that occurred on the server. */
    apiError?: Error
    /** Query ID associated with the error, when available from the insight response. */
    queryId?: string
    /** Whether the card should be highlighted with a blue border. */
    highlighted?: boolean
    /** Whether loading timed out. */
    timedOut?: boolean
    /** Whether the editing controls should be enabled or not. */
    showEditingControls?: boolean
    refreshAfterDisplayOptionsChange?: (insight: InsightModel) => void
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
    keepMountedDuringInteraction?: boolean
    renderVizWhenMounted?: boolean
    onOverlayVisibilityChange?: (visible: boolean) => void
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
    tile?: DashboardTile
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
    /** Project the insight belongs to, when that is not the current project. The card's links then open it there. */
    projectId?: number
    /** Time zone of `projectId`, so the chart places that project's annotations on the right day. */
    projectTimezone?: string
    /** Shown above the title, for a card that has to name where its insight comes from. */
    contextHeading?: JSX.Element | null
}

function InsightCardInternal(
    {
        tile,
        insight,
        dashboardId,
        canEditDashboard,
        ribbonColor,
        loadingQueued,
        loading,
        apiError,
        apiErrored,
        queryId,
        timedOut,
        highlighted,
        refreshAfterDisplayOptionsChange,
        showResizeHandles,
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
        keepMountedDuringInteraction,
        renderVizWhenMounted,
        onOverlayVisibilityChange,
        filtersOverride,
        variablesOverride,
        children,
        projectId,
        projectTimezone,
        contextHeading,
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
    const { ref: inViewRef, inView } = useInView({ rootMargin: '500px', skip: renderVizWhenMounted })
    const { isVisible: isPageVisible } = usePageVisibility()

    /**
     * Hidden canvas visualizations are unmounted to release their backing stores and reduce the risk of context loss.
     * When the page is hidden, DOM and SVG visualizations stay mounted to preserve state such as table scroll position.
     * See https://wiki.whatwg.org/wiki/Canvas_Context_Loss_and_Restoration.
     */
    const shouldRenderViz = shouldRenderInsightCardViz({
        isStorybook: IS_STORYBOOK,
        placement,
        inView: inView || !!keepMountedDuringInteraction || !!renderVizWhenMounted,
        isPageVisible,
        query: insight.query,
    })

    const mergedRefs = useMergeRefs([ref, inViewRef])

    const { theme } = useValues(themeLogic)

    const canEditInsight = insight.user_access_level
        ? accessLevelSatisfied(AccessControlResourceType.Insight, insight.user_access_level, AccessControlLevel.Editor)
        : true
    const canPersistDisplayOptions = !!dashboardId && canEditInsight
    const refreshAfterDisplayOptionsChangeRef = useRef(refreshAfterDisplayOptionsChange)
    refreshAfterDisplayOptionsChangeRef.current = refreshAfterDisplayOptionsChange
    const handleRefreshAfterDisplayOptionsChange = useCallback((updatedInsight: InsightModel): void => {
        refreshAfterDisplayOptionsChangeRef.current?.(updatedInsight)
    }, [])

    // Base props without setQuery — used to mount insightDataLogic and retrieve the
    // persistDisplayOptions action before wiring it back in as setQuery below.
    const insightLogicPropsBase: InsightLogicProps = useMemo(
        () => ({
            dashboardItemId: insight.short_id,
            dashboardId: dashboardId,
            cachedInsight: insight,
            loadPriority,
            doNotLoad,
            refreshAfterDisplayOptionsChange: handleRefreshAfterDisplayOptionsChange,
            sourceProject: projectId !== undefined ? { id: projectId, timezone: projectTimezone } : undefined,
        }),
        [
            insight,
            dashboardId,
            loadPriority,
            doNotLoad,
            handleRefreshAfterDisplayOptionsChange,
            projectId,
            projectTimezone,
        ]
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
    const { insightDataLoading, insightDataError } = useValues(insightDataLogic(insightLogicProps))

    const [, setCooldownTick] = useState(0)
    // The embedded query stores its own failure in insightDataLogic and does not set the apiError prop.
    const capacityRetryAt = getCapacityRetryAt(apiErrored ? apiError : null, insightDataError)
    const { secondsLeft: retrySecondsLeft, disabledReason: refreshDisabledReason } = getRetryCooldown(capacityRetryAt)
    useInterval(() => setCooldownTick((tick) => tick + 1), retrySecondsLeft > 0 ? 1000 : null)
    const refreshAfterCooldown = useCallback((): void => {
        if (!capacityRetryAt || Date.now() >= capacityRetryAt) {
            refresh?.()
        }
    }, [refresh, capacityRetryAt])

    if (insightLoading || insightDataLoading) {
        loading = true
    }

    const [areDetailsShown, setAreDetailsShown] = useState(false)
    const [compactInfoVisible, setCompactInfoVisible] = useState(false)
    const [alertModal, setAlertModal] = useState<AlertModalState | null>(null)
    useEffect(() => {
        onOverlayVisibilityChange?.(areDetailsShown || compactInfoVisible || alertModal !== null)
    }, [areDetailsShown, compactInfoVisible, alertModal, onOverlayVisibilityChange])
    const openCreateAlertModal = useCallback(() => setAlertModal({}), [])
    const openEditAlertModal = useCallback((alertId: AlertType['id']) => setAlertModal({ alertId }), [])
    const openCreateAnomalyAlertModal = useCallback(() => setAlertModal({ defaultToAnomalyDetection: true }), [])
    const closeAlertModal = useCallback(() => setAlertModal(null), [])
    const hasResults = !!insight?.result || !!(insight as any)?.results
    const sharedView = isSharedView()

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
                    titleStatus={403}
                    excludeDetail
                />
            )
        }

        if (apiErrored) {
            const validationError = extractValidationError(apiError)
            if (validationError) {
                return (
                    <InsightValidationError
                        detail={validationError}
                        validationErrorCode={extractValidationErrorCode(apiError)}
                        query={insight.query}
                        excludeActions={sharedView}
                        placement={placement}
                    />
                )
            } else if (apiError instanceof ApiError) {
                return (
                    <InsightErrorState
                        title={apiError.detail}
                        titleStatus={apiError.status}
                        queryId={apiError.data?.queryId ?? queryId}
                        retryAfter={apiError.formattedRetryAfter}
                        retryAfterTimestamp={capacityRetryAt}
                        retryLoading={loading || !!loadingQueued}
                        query={insight.query}
                        excludeActions={sharedView}
                        placement={placement}
                        onRetry={sharedView || !refresh ? undefined : refreshAfterCooldown}
                    />
                )
            }
            return <InsightErrorState />
        }

        // Below the failure branch on purpose: a tile whose query is known to have failed must show
        // that, even while the next attempt is already queued. The other way round, the spinner wins
        // for as long as the retries run and the user cannot tell a dead tile from a slow one.
        if (!hasResults && loadingQueued) {
            return <InsightLoadingState insightProps={insightLogicProps} />
        }

        if (timedOut) {
            return <InsightTimeoutState />
        }

        return null
    })()

    // Keep the Query element stable so grid updates do not remount the chart.
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

    const vizContent = shouldRenderViz ? (
        <div className="InsightCard__viz">
            <div className="InsightCard__vizInner">{vizInner}</div>
        </div>
    ) : (
        <InsightVisualizationSkeleton query={insight.query} />
    )

    return (
        <div
            className={clsx(
                'DashboardTileCard InsightCard border',
                highlighted && 'InsightCard--highlighted',
                areDetailsShown && 'InsightCard--details-shown',
                className
            )}
            data-attr="insight-card"
            {...{ [INSIGHT_CARD_KEY_ATTR]: insightCardKey(insight, tile) }}
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
                        projectId={projectId}
                        contextHeading={contextHeading}
                        ribbonColor={ribbonColor}
                        dashboardId={dashboardId}
                        canEditDashboard={canEditDashboard}
                        persistDisplayOptions={canPersistDisplayOptions ? persistDisplayOptions : undefined}
                        refreshAfterDisplayOptionsChange={handleRefreshAfterDisplayOptionsChange}
                        updateColor={updateColor}
                        toggleShowDescription={toggleShowDescription}
                        removeFromDashboard={removeFromDashboard}
                        deleteWithUndo={deleteWithUndo}
                        refresh={refresh ? refreshAfterCooldown : undefined}
                        refreshDisabledReason={refreshDisabledReason}
                        loadingQueued={loadingQueued}
                        loading={loading}
                        rename={rename}
                        duplicate={duplicate}
                        setOverride={setOverride}
                        moveToDashboard={moveToDashboard}
                        copyToDashboard={copyToDashboard}
                        areDetailsShown={areDetailsShown}
                        setAreDetailsShown={setAreDetailsShown}
                        onInfoVisibilityChange={setCompactInfoVisible}
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
