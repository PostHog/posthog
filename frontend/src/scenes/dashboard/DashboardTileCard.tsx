import 'lib/components/Cards/InsightCard/InsightCard.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import React from 'react'
import { useInView } from 'react-intersection-observer'

import { ApiError } from 'lib/api'
import { Resizeable } from 'lib/components/Cards/CardMeta'
import { ResizeHandle1D, ResizeHandle2D } from 'lib/components/Cards/handles'
import {
    InsightErrorState,
    InsightLoadingState,
    InsightTimeoutState,
    InsightValidationError,
} from 'scenes/insights/EmptyStates'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { Query } from '~/queries/Query/Query'
import { extractValidationError } from '~/queries/nodes/InsightViz/utils'
import { DashboardFilter, HogQLVariable } from '~/queries/schema/schema-general'
import {
    DashboardBasicType,
    DashboardPlacement,
    DashboardTile,
    DashboardType,
    InsightColor,
    InsightLogicProps,
    QueryBasedInsightModel,
} from '~/types'

import { BreakdownColorConfig } from './DashboardInsightColorsModal'
import { DashboardTileMeta } from './DashboardTileMeta'
import { dashboardFiltersLogic } from './dashboardFiltersLogic'
import { dashboardQueryCacheLogic } from './dashboardQueryCacheLogic'

export interface DashboardTileCardProps extends Resizeable {
    insight: QueryBasedInsightModel
    tile?: DashboardTile<QueryBasedInsightModel>
    dashboardId?: DashboardType['id']
    ribbonColor?: InsightColor | null
    loadingQueued?: boolean
    loading?: boolean
    apiErrored?: boolean
    apiError?: Error
    timedOut?: boolean
    highlighted?: boolean
    showEditingControls?: boolean
    showDetailsControls?: boolean
    updateColor?: (color: DashboardTile['color']) => void
    removeFromDashboard?: () => void
    refresh?: () => void
    refreshEnabled?: boolean
    rename?: () => void
    duplicate?: () => void
    setOverride?: () => void
    moveToDashboard?: (dashboard: DashboardBasicType) => void
    placement: DashboardPlacement | 'SavedInsightGrid'
    loadPriority?: number
    className?: string
    style?: React.CSSProperties
    children?: React.ReactNode
    surveyOpportunity?: boolean
    // Passed by DashboardItems for InsightCard compatibility; read directly from logics instead
    filtersOverride?: DashboardFilter
    variablesOverride?: Record<string, HogQLVariable>
    breakdownColorOverride?: BreakdownColorConfig[]
    dataColorThemeId?: number | null
}

function DashboardTileCardInternal(
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
        canResizeWidth,
        showEditingControls,
        removeFromDashboard,
        refresh,
        refreshEnabled,
        duplicate,
        moveToDashboard,
        className,
        placement,
        children,
        ...divProps
    }: DashboardTileCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element | null {
    const { ref: inViewRef, inView } = useInView({ triggerOnce: true })
    const { theme } = useValues(themeLogic)

    // Read filter/variable overrides from dashboardFiltersLogic directly
    const filtersLogicProps = dashboardId ? { id: dashboardId } : { id: 0 }
    const { effectiveEditBarFilters, effectiveDashboardVariableOverrides } = useValues(
        dashboardFiltersLogic(filtersLogicProps)
    )

    // Check query cache for pre-existing results
    const { getCachedResult } = useValues(dashboardQueryCacheLogic(filtersLogicProps))
    const cachedResult = dashboardId
        ? getCachedResult(insight.id, effectiveEditBarFilters, effectiveDashboardVariableOverrides)
        : null

    // Use cached result or fall back to the insight's own result
    const insightWithResult: QueryBasedInsightModel = cachedResult ? { ...insight, result: cachedResult } : insight

    const hasResults = !!insightWithResult?.result || !!(insightWithResult as any)?.results

    // Minimal insightProps for Query context — no insightLogic mount needed
    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: insight.short_id,
        dashboardId,
        cachedInsight: insightWithResult,
        doNotLoad: true,
    }

    const BlockingEmptyState = (() => {
        if (!hasResults && loadingQueued) {
            return <InsightLoadingState insightProps={insightLogicProps} />
        }
        if (apiErrored) {
            const validationError = extractValidationError(apiError)
            if (validationError) {
                return <InsightValidationError detail={validationError} />
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

    return (
        <div
            className={clsx('InsightCard border', highlighted && 'InsightCard--highlighted', className)}
            data-attr="dashboard-tile-card"
            {...divProps}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ ...divProps?.style, ...theme?.boxStyle }}
            ref={ref}
        >
            <ErrorBoundary exceptionProps={{ feature: 'insight' }}>
                <DashboardTileMeta
                    insight={insightWithResult}
                    tile={tile}
                    dashboardId={dashboardId}
                    ribbonColor={ribbonColor}
                    loading={loading}
                    loadingQueued={loadingQueued}
                    apiErrored={apiErrored}
                    showEditingControls={showEditingControls}
                    refresh={refresh}
                    refreshEnabled={refreshEnabled}
                    duplicate={duplicate}
                    removeFromDashboard={removeFromDashboard}
                    moveToDashboard={moveToDashboard}
                    placement={placement}
                />
                {inView ? (
                    <div className="InsightCard__viz" ref={inViewRef}>
                        {BlockingEmptyState ? (
                            BlockingEmptyState
                        ) : (
                            <Query
                                query={insightWithResult.query}
                                cachedResults={insightWithResult}
                                context={{
                                    insightProps: insightLogicProps,
                                }}
                                readOnly
                                embedded
                                inSharedMode={placement === DashboardPlacement.Public}
                                variablesOverride={effectiveDashboardVariableOverrides}
                                editMode={false}
                            />
                        )}
                    </div>
                ) : (
                    <div ref={inViewRef} />
                )}
                {showResizeHandles && (
                    <>
                        {canResizeWidth ? <ResizeHandle1D orientation="vertical" /> : null}
                        <ResizeHandle1D orientation="horizontal" />
                        {canResizeWidth ? <ResizeHandle2D /> : null}
                    </>
                )}
                {children}
            </ErrorBoundary>
        </div>
    )
}

export const DashboardTileCard = React.forwardRef(DashboardTileCardInternal) as (
    props: DashboardTileCardProps & React.RefAttributes<HTMLDivElement>
) => ReturnType<typeof DashboardTileCardInternal>
