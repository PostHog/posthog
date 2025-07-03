import './InsightCard.scss'

import { useMergeRefs } from '@floating-ui/react'
import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { Resizeable } from 'lib/components/Cards/CardMeta'
import { FEATURE_FLAGS } from 'lib/constants'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React, { useState } from 'react'
import { Layout } from 'react-grid-layout'
import { useInView } from 'react-intersection-observer'
import { BreakdownColorConfig } from 'scenes/dashboard/DashboardInsightColorsModal'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { Query } from '~/queries/Query/Query'
import { HogQLVariable } from '~/queries/schema/schema-general'
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
    /** Dashboard variables to override the ones in the insight */
    variablesOverride?: Record<string, HogQLVariable>
    /** Dashboard breakdown colors to override the ones in the insight */
    breakdownColorOverride?: BreakdownColorConfig[]
    /** Dashboard color theme to override the ones in the insight */
    dataColorThemeId?: number | null
    className?: string
    style?: React.CSSProperties
    children?: React.ReactNode
    noCache?: boolean
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
        moreButtons,
        placement,
        loadPriority,
        doNotLoad,
        variablesOverride,
        children,
        noCache,
        breakdownColorOverride: _breakdownColorOverride,
        dataColorThemeId: _dataColorThemeId,
        ...divProps
    }: InsightCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    const { ref: inViewRef, inView } = useInView()
    const { isVisible: isPageVisible } = usePageVisibility()
    /** Wether the page is active and the line graph is currently in view. Used to free resources, by not rendering
     * insight cards that aren't visible. See also https://wiki.whatwg.org/wiki/Canvas_Context_Loss_and_Restoration.
     */
    const isVisible =
        featureFlags[FEATURE_FLAGS.EXPERIMENTAL_DASHBOARD_ITEM_RENDERING] === true ? inView && isPageVisible : true

    const mergedRefs = useMergeRefs([ref, inViewRef])

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
            style={{ ...divProps?.style, ...theme?.boxStyle }}
            ref={mergedRefs}
        >
            {isVisible ? (
                <ErrorBoundary exceptionProps={{ feature: 'insight' }}>
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
                            variablesOverride={variablesOverride}
                        />
                        <div className="InsightCard__viz">
                            <Query
                                query={insight.query}
                                cachedResults={noCache ? undefined : insight}
                                context={{
                                    insightProps: insightLogicProps,
                                }}
                                readOnly
                                embedded
                                inSharedMode={placement === DashboardPlacement.Public}
                                variablesOverride={variablesOverride}
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
                    {children /* Extras, specifically resize handles injected by ReactGridLayout */}
                </ErrorBoundary>
            ) : null}
        </div>
    )
}
export const InsightCard = React.forwardRef(InsightCardInternal) as typeof InsightCardInternal
