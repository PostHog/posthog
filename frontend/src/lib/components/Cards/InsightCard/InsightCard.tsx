import './InsightCard.scss'

import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { Resizeable } from 'lib/components/Cards/CardMeta'
import React, { useState } from 'react'
import { Layout } from 'react-grid-layout'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { Query } from '~/queries/Query/Query'
import {
    DashboardBasicType,
    DashboardPlacement,
    DashboardTile,
    DashboardType,
    InsightColor,
    InsightLogicProps,
    QueryBasedInsightModel,
} from '~/types'

import { ResizeHandle1D, ResizeHandle2D } from '../handles'
import { InsightMeta } from './InsightMeta'

export interface InsightCardProps extends Resizeable, React.HTMLAttributes<HTMLDivElement> {
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
    /** Whether the card should be highlighted with a blue border. */
    highlighted?: boolean
    /** Whether loading timed out. */
    timedOut?: boolean
    /** Whether the editing controls should be enabled or not. */
    showEditingControls?: boolean
    /** Whether the  controls for showing details should be enabled or not. */
    showDetailsControls?: boolean
    /** Layout of the card on a grid. */
    layout?: Layout
    ribbonColor?: InsightColor | null
    updateColor?: (newColor: DashboardTile['color']) => void
    removeFromDashboard?: () => void
    deleteWithUndo?: () => Promise<void>
    refresh?: () => void
    refreshEnabled?: boolean
    rename?: () => void
    duplicate?: () => void
    moveToDashboard?: (dashboard: DashboardBasicType) => void
    /** buttons to add to the "more" menu on the card**/
    moreButtons?: JSX.Element | null
    placement: DashboardPlacement | 'SavedInsightGrid'
    /** Priority for loading the insight, lower is earlier. */
    loadPriority?: number
    doNotLoad?: boolean
}

function InsightCardInternal(
    {
        insight,
        dashboardId,
        ribbonColor,
        loadingQueued,
        loading,
        apiErrored,
        timedOut,
        highlighted,
        showResizeHandles,
        canResizeWidth,
        showEditingControls,
        showDetailsControls,
        updateColor,
        removeFromDashboard,
        deleteWithUndo,
        refresh,
        refreshEnabled,
        rename,
        duplicate,
        moveToDashboard,
        className,
        children,
        moreButtons,
        placement,
        loadPriority,
        doNotLoad,
        ...divProps
    }: InsightCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const { theme } = useValues(themeLogic)
    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: insight.short_id,
        dashboardId: dashboardId,
        cachedInsight: insight,
        loadPriority,
        doNotLoad,
    }

    const { insightLoading } = useValues(insightLogic(insightLogicProps))
    const { insightDataLoading } = useValues(insightDataLogic(insightLogicProps))

    if (insightLoading || insightDataLoading) {
        loading = true
    }

    const [areDetailsShown, setAreDetailsShown] = useState(false)

    return (
        <div
            className={clsx('InsightCard border', highlighted && 'InsightCard--highlighted', className)}
            data-attr="insight-card"
            {...divProps}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ ...(divProps?.style ?? {}), ...(theme?.boxStyle ?? {}) }}
            ref={ref}
        >
            <ErrorBoundary tags={{ feature: 'insight' }}>
                <BindLogic logic={insightLogic} props={insightLogicProps}>
                    <InsightMeta
                        insight={insight}
                        ribbonColor={ribbonColor}
                        dashboardId={dashboardId}
                        updateColor={updateColor}
                        removeFromDashboard={removeFromDashboard}
                        deleteWithUndo={deleteWithUndo}
                        refresh={refresh}
                        refreshEnabled={refreshEnabled}
                        loading={loadingQueued || loading}
                        rename={rename}
                        duplicate={duplicate}
                        moveToDashboard={moveToDashboard}
                        areDetailsShown={areDetailsShown}
                        setAreDetailsShown={setAreDetailsShown}
                        showEditingControls={showEditingControls}
                        showDetailsControls={showDetailsControls}
                        moreButtons={moreButtons}
                    />
                    <div className="InsightCard__viz">
                        <Query
                            query={insight.query}
                            cachedResults={insight}
                            context={{
                                insightProps: insightLogicProps,
                            }}
                            readOnly
                            embedded
                            inSharedMode={placement === DashboardPlacement.Public}
                        />
                    </div>
                </BindLogic>
                {showResizeHandles && (
                    <>
                        {canResizeWidth ? <ResizeHandle1D orientation="vertical" /> : null}
                        <ResizeHandle1D orientation="horizontal" />
                        {canResizeWidth ? <ResizeHandle2D /> : null}
                    </>
                )}
                {children /* Extras, such as resize handles */}
            </ErrorBoundary>
        </div>
    )
}
export const InsightCard = React.forwardRef(InsightCardInternal) as typeof InsightCardInternal
