import { Alert } from 'antd'
import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { capitalizeFirstLetter, dateFilterToText, Loading } from 'lib/utils'
import React from 'react'
import { Layout } from 'react-grid-layout'
import { displayMap, getDisplayedType } from 'scenes/dashboard/DashboardItem'
import { UNNAMED_INSIGHT_NAME } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardType, InsightColor, InsightLogicProps, InsightModel, InsightType } from '~/types'
import { Splotch, SplotchColor } from '../icons/Splotch'
import { LemonButton, LemonButtonWithPopup } from '../LemonButton'
import { More } from '../LemonButton/More'
import { LemonSpacer } from '../LemonRow'
import { Link } from '../Link'
import { ObjectTags } from '../ObjectTags'
import { ResizeHandle1D, ResizeHandle2D } from './handles'
import './InsightCard.scss'

export interface InsightCardProps extends React.HTMLAttributes<HTMLDivElement> {
    /** Insight to display. */
    insight: InsightModel
    /** Whether the insight is loading. */
    loading: boolean
    /** Whether loading the insight resulted in an error. */
    apiError: boolean
    /** Whether the card should be highlighted with a blue border. */
    highlighted: boolean
    showResizeHandles: boolean
    /** Layout of the card on a grid. */
    layout?: Layout
    updateColor: (newColor: InsightModel['color']) => void
    removeFromDashboard: () => void
    refresh: () => void
    rename: () => void
    duplicate: () => void
    moveToDashboard: (dashboardId: DashboardType['id']) => void
}

function InsightMeta({
    insight,
    updateColor,
    removeFromDashboard,
    refresh,
    rename,
    duplicate,
    moveToDashboard,
}: Pick<
    InsightCardProps,
    'insight' | 'updateColor' | 'removeFromDashboard' | 'refresh' | 'rename' | 'duplicate' | 'moveToDashboard'
>): JSX.Element {
    const { short_id, name, description, tags, color, filters, dashboard } = insight

    const { nameSortedDashboards } = useValues(dashboardsModel)
    const otherDashboards: DashboardType[] = nameSortedDashboards.filter((d: DashboardType) => d.id !== dashboard)

    return (
        <div className="InsightMeta">
            {color && color !== InsightColor.White /* White has historically meant no color synonymously to null */ && (
                <div className={clsx('InsightMeta__ribbon', color)} />
            )}
            <div className="InsightMeta__main">
                <div className="InsightMeta__top">
                    <h5>
                        {filters.insight || InsightType.TRENDS} •{' '}
                        {dateFilterToText(filters.date_from, filters.date_to, 'Last 7 days')}
                    </h5>
                    <div className="InsightMeta__controls">
                        <More
                            overlay={
                                <>
                                    <LemonButton type="stealth" to={urls.insightView(short_id)} fullWidth>
                                        View
                                    </LemonButton>
                                    <LemonButton type="stealth" onClick={() => refresh()} fullWidth>
                                        Refresh
                                    </LemonButton>
                                    <LemonButtonWithPopup
                                        type="stealth"
                                        popup={{
                                            overlay: Object.values(InsightColor).map((availableColor) => (
                                                <LemonButton
                                                    key={availableColor}
                                                    type={
                                                        availableColor === (color || InsightColor.White)
                                                            ? 'highlighted'
                                                            : 'stealth'
                                                    }
                                                    onClick={() => updateColor(availableColor)}
                                                    icon={
                                                        availableColor !== InsightColor.White ? (
                                                            <Splotch color={availableColor as string as SplotchColor} />
                                                        ) : null
                                                    }
                                                    fullWidth
                                                >
                                                    {availableColor !== InsightColor.White
                                                        ? capitalizeFirstLetter(availableColor)
                                                        : 'No color'}
                                                </LemonButton>
                                            )),
                                            placement: 'right-start',
                                            fallbackPlacements: ['left-start'],
                                        }}
                                        fullWidth
                                    >
                                        Set color
                                    </LemonButtonWithPopup>
                                    {otherDashboards.length > 0 && (
                                        <LemonButtonWithPopup
                                            type="stealth"
                                            popup={{
                                                overlay: otherDashboards.map((otherDashboard) => (
                                                    <LemonButton
                                                        key={otherDashboard.id}
                                                        type="stealth"
                                                        onClick={() => moveToDashboard(otherDashboard.id)}
                                                        fullWidth
                                                    >
                                                        {otherDashboard.name || <i>Untitled</i>}
                                                    </LemonButton>
                                                )),
                                                placement: 'right-start',
                                                fallbackPlacements: ['left-start'],
                                            }}
                                            fullWidth
                                        >
                                            Move to
                                        </LemonButtonWithPopup>
                                    )}
                                    <LemonSpacer />
                                    <LemonButton type="stealth" to={urls.insightEdit(short_id)} fullWidth>
                                        Edit
                                    </LemonButton>
                                    <LemonButton type="stealth" onClick={rename} fullWidth>
                                        Rename
                                    </LemonButton>
                                    <LemonButton type="stealth" onClick={duplicate} fullWidth>
                                        Duplicate
                                    </LemonButton>
                                    <LemonSpacer />
                                    <LemonButton
                                        type="stealth"
                                        style={{ color: 'var(--danger)' }}
                                        onClick={removeFromDashboard}
                                        fullWidth
                                    >
                                        Remove from dashboard
                                    </LemonButton>
                                </>
                            }
                        />
                    </div>
                </div>
                <Link to={urls.insightView(short_id)}>
                    <h4 title={name} data-attr="insight-card-title">
                        {name || <i>{UNNAMED_INSIGHT_NAME}</i>}
                    </h4>
                </Link>
                <div className="InsightMeta__description">{description || <i>No description</i>}</div>
                {tags.length > 0 && <ObjectTags tags={tags} staticOnly />}
            </div>
        </div>
    )
}

function InsightViz({ insight, loading }: Pick<InsightCardProps, 'insight' | 'loading' | 'apiError'>): JSX.Element {
    const { short_id, filters, result: cachedResults } = insight

    const displayedType = getDisplayedType(filters)
    const VizComponent = displayMap[displayedType].element

    return (
        <div className="InsightViz">
            {loading && <Loading />}
            <Alert.ErrorBoundary message="Insight visualization errored. We're sorry for the interruption.">
                <VizComponent dashboardItemId={short_id} cachedResults={cachedResults} filters={filters} />
            </Alert.ErrorBoundary>
        </div>
    )
}

function InsightCardInternal(
    {
        insight,
        loading,
        apiError,
        highlighted,
        showResizeHandles,
        updateColor,
        removeFromDashboard,
        refresh,
        rename,
        duplicate,
        moveToDashboard,
        className,
        children,
        ...divProps
    }: InsightCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const { short_id, filters, result: cachedResults } = insight

    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: short_id,
        filters,
        cachedResults,
        doNotLoad: true,
    }

    return (
        <div
            className={clsx('InsightCard', highlighted && 'InsightCard--highlighted', className)}
            data-attr="insight-card"
            {...divProps}
            ref={ref}
        >
            <InsightMeta
                insight={insight}
                updateColor={updateColor}
                removeFromDashboard={removeFromDashboard}
                refresh={refresh}
                rename={rename}
                duplicate={duplicate}
                moveToDashboard={moveToDashboard}
            />
            <BindLogic logic={insightLogic} props={insightLogicProps}>
                <InsightViz insight={insight} loading={loading} apiError={apiError} />
            </BindLogic>
            {showResizeHandles && (
                <>
                    <ResizeHandle1D orientation="vertical" />
                    <ResizeHandle1D orientation="horizontal" />
                    <ResizeHandle2D />
                </>
            )}
            {children /* Extras, such as resize handles */}
        </div>
    )
}
export const InsightCard = React.forwardRef(InsightCardInternal) as typeof InsightCardInternal
