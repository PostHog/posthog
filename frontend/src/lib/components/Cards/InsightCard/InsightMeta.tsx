import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'

import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

import { CardMeta } from 'lib/components/Cards/CardMeta'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Splotch, SplotchColor } from 'lib/lemon-ui/Splotch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'
import { isDataVisualizationNode } from '~/queries/utils'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DashboardPlacement,
    DashboardTile,
    ExporterFormat,
    InsightColor,
    QueryBasedInsightModel,
} from '~/types'

import { DataWarehouseSyncNotice } from './DataWarehouseSyncNotice'
import { InsightCardProps } from './InsightCard'
import { InsightDetails } from './InsightDetails'

interface InsightMetaProps
    extends Pick<
        InsightCardProps,
        | 'ribbonColor'
        | 'updateColor'
        | 'removeFromDashboard'
        | 'deleteWithUndo'
        | 'refresh'
        | 'refreshEnabled'
        | 'loading'
        | 'loadingQueued'
        | 'rename'
        | 'setOverride'
        | 'duplicate'
        | 'dashboardId'
        | 'moveToDashboard'
        | 'showEditingControls'
        | 'showDetailsControls'
        | 'moreButtons'
        | 'filtersOverride'
        | 'variablesOverride'
        | 'placement'
    > {
    tile?: DashboardTile<QueryBasedInsightModel>
    insight: QueryBasedInsightModel
    areDetailsShown?: boolean
    setAreDetailsShown?: React.Dispatch<React.SetStateAction<boolean>>
}

export function InsightMeta({
    tile,
    insight,
    ribbonColor,
    dashboardId,
    updateColor,
    filtersOverride,
    variablesOverride,
    removeFromDashboard,
    deleteWithUndo,
    refresh,
    refreshEnabled,
    loading,
    loadingQueued,
    rename,
    duplicate,
    setOverride,
    moveToDashboard,
    areDetailsShown,
    setAreDetailsShown,
    showEditingControls = true,
    showDetailsControls = true,
    moreButtons,
    placement,
}: InsightMetaProps): JSX.Element {
    const { short_id, name, dashboards, next_allowed_client_refresh: nextAllowedClientRefresh } = insight
    const { insightProps, insightFeedback } = useValues(insightLogic)
    const { setInsightFeedback } = useActions(insightLogic)
    const { exportContext } = useValues(insightDataLogic(insightProps))
    const { samplingFactor } = useValues(insightVizDataLogic(insightProps))
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const { featureFlags } = useValues(featureFlagLogic)

    const otherDashboards = nameSortedDashboards.filter((d) => !dashboards?.includes(d.id))

    const canViewInsight = insight.user_access_level
        ? accessLevelSatisfied(AccessControlResourceType.Insight, insight.user_access_level, AccessControlLevel.Viewer)
        : true
    const canEditInsight =
        insight.user_access_level && canViewInsight
            ? accessLevelSatisfied(
                  AccessControlResourceType.Insight,
                  insight.user_access_level,
                  AccessControlLevel.Editor
              )
            : true

    // For dashboard-specific actions (remove from dashboard, change tile color), check dashboard permissions
    const currentDashboard = dashboardId ? nameSortedDashboards.find((d) => d.id === dashboardId) : null
    const canEditDashboard = currentDashboard?.user_access_level
        ? accessLevelSatisfied(
              AccessControlResourceType.Dashboard,
              currentDashboard.user_access_level,
              AccessControlLevel.Editor
          )
        : true

    const canAccessTileOverrides = !!featureFlags[FEATURE_FLAGS.DASHBOARD_TILE_OVERRIDES]

    const summary = useSummarizeInsight()(insight.query)

    // Feedback buttons for Customer Analytics
    const feedbackButtons =
        placement === DashboardPlacement.CustomerAnalytics && featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS] ? (
            <div className="flex gap-0">
                <LemonButton
                    size="small"
                    icon={<IconThumbsUp className={insightFeedback === 'liked' ? 'text-accent' : ''} />}
                    onClick={() => setInsightFeedback('liked')}
                    tooltip="Like this insight"
                    disabledReason={insightFeedback === 'liked' ? 'Already liked' : ''}
                />
                <LemonButton
                    size="small"
                    icon={<IconThumbsDown className={insightFeedback === 'disliked' ? 'text-accent' : ''} />}
                    onClick={() => setInsightFeedback('disliked')}
                    tooltip="Dislike this insight"
                    disabledReason={insightFeedback === 'disliked' ? 'Already disliked' : ''}
                />
            </div>
        ) : null

    // If user can't view the insight, show minimal interface
    if (!canViewInsight) {
        return (
            <CardMeta
                ribbonColor={ribbonColor}
                showEditingControls={false}
                showDetailsControls={false}
                setAreDetailsShown={setAreDetailsShown}
                areDetailsShown={areDetailsShown}
                detailsTooltip="Show insight details, such as creator, last edit, and applied filters."
                topHeading={null}
                content={
                    <InsightMetaContent
                        link={undefined}
                        title="Access denied"
                        fallbackTitle={summary}
                        description={undefined}
                        loading={loading}
                        loadingQueued={loadingQueued}
                        tags={[]}
                        query={undefined}
                    />
                }
                metaDetails={null}
                samplingFactor={samplingFactor}
            />
        )
    }

    const refreshDisabledReason =
        nextAllowedClientRefresh && dayjs(nextAllowedClientRefresh).isAfter(dayjs())
            ? 'You are viewing the most recent calculated results.'
            : loading || loadingQueued || !refreshEnabled
              ? 'Refreshing...'
              : undefined

    return (
        <CardMeta
            ribbonColor={ribbonColor}
            showEditingControls={showEditingControls}
            showDetailsControls={showDetailsControls}
            setAreDetailsShown={setAreDetailsShown}
            areDetailsShown={areDetailsShown}
            detailsTooltip="Show insight details, such as creator, last edit, and applied filters."
            topHeading={
                <TopHeading
                    query={insight.query}
                    lastRefresh={insight.last_refresh}
                    hasTileOverrides={Object.keys(tile?.filters_overrides ?? {}).length > 0}
                />
            }
            content={
                <InsightMetaContent
                    link={urls.insightView(
                        short_id,
                        dashboardId,
                        variablesOverride,
                        filtersOverride,
                        tile?.filters_overrides
                    )}
                    title={name}
                    fallbackTitle={summary}
                    description={insight.description}
                    loading={loading}
                    loadingQueued={loadingQueued}
                    tags={insight.tags}
                    query={insight.query}
                />
            }
            metaDetails={
                <InsightDetails query={insight.query} footerInfo={insight} variablesOverride={variablesOverride} />
            }
            samplingFactor={samplingFactor}
            moreButtons={
                <>
                    {/* Insight related */}
                    {canEditInsight && (
                        <>
                            <LemonButton
                                to={
                                    isDataVisualizationNode(insight.query)
                                        ? urls.sqlEditor(undefined, undefined, short_id)
                                        : urls.insightEdit(short_id)
                                }
                                fullWidth
                            >
                                Edit
                            </LemonButton>
                            <LemonButton onClick={rename} fullWidth>
                                Rename
                            </LemonButton>
                            {canAccessTileOverrides && tile && (
                                <LemonButton onClick={setOverride} fullWidth>
                                    Set override
                                </LemonButton>
                            )}
                        </>
                    )}
                    <LemonButton
                        onClick={duplicate}
                        fullWidth
                        data-attr={
                            dashboardId ? 'duplicate-insight-from-dashboard' : 'duplicate-insight-from-card-list-view'
                        }
                    >
                        Duplicate
                    </LemonButton>

                    {/* Dashboard related */}
                    {canEditDashboard && (
                        <>
                            <LemonDivider />
                            {updateColor && (
                                <LemonButtonWithDropdown
                                    dropdown={{
                                        overlay: Object.values(InsightColor).map((availableColor) => (
                                            <LemonButton
                                                key={availableColor}
                                                active={availableColor === (ribbonColor || InsightColor.White)}
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
                                        actionable: true,
                                        closeParentPopoverOnClickInside: true,
                                    }}
                                    fullWidth
                                >
                                    Set color
                                </LemonButtonWithDropdown>
                            )}
                            {moveToDashboard && otherDashboards.length > 0 && (
                                <LemonButtonWithDropdown
                                    dropdown={{
                                        overlay: otherDashboards.map((otherDashboard) => (
                                            <LemonButton
                                                key={otherDashboard.id}
                                                onClick={() => {
                                                    moveToDashboard(otherDashboard)
                                                }}
                                                fullWidth
                                            >
                                                {otherDashboard.name || <i>Untitled</i>}
                                            </LemonButton>
                                        )),
                                        placement: 'right-start',
                                        fallbackPlacements: ['left-start'],
                                        actionable: true,
                                        closeParentPopoverOnClickInside: true,
                                    }}
                                    fullWidth
                                >
                                    Move to
                                </LemonButtonWithDropdown>
                            )}
                            {removeFromDashboard && (
                                <LemonButton status="danger" onClick={removeFromDashboard} fullWidth>
                                    Remove from dashboard
                                </LemonButton>
                            )}
                        </>
                    )}

                    {/* Insight deletion - separate from dashboard actions */}
                    {canEditInsight && !removeFromDashboard && deleteWithUndo && (
                        <>
                            <LemonDivider />
                            <LemonButton
                                status="danger"
                                onClick={() => {
                                    void (async () => {
                                        try {
                                            await deleteWithUndo?.()
                                        } catch (error: any) {
                                            lemonToast.error(`Failed to delete insight meta: ${error.detail}`)
                                        }
                                    })()
                                }}
                                fullWidth
                            >
                                Delete insight
                            </LemonButton>
                        </>
                    )}

                    {/* Data related */}
                    {exportContext ? (
                        <>
                            <LemonDivider />
                            <ExportButton
                                fullWidth
                                items={[
                                    {
                                        export_format: ExporterFormat.PNG,
                                        insight: insight.id,
                                        dashboard: insightProps.dashboardId,
                                    },
                                    {
                                        export_format: ExporterFormat.CSV,
                                        export_context: exportContext,
                                    },
                                    {
                                        export_format: ExporterFormat.XLSX,
                                        export_context: exportContext,
                                    },
                                ]}
                            />
                        </>
                    ) : null}
                    <>
                        {refresh && (
                            <LemonButton
                                onClick={() => {
                                    refresh()
                                }}
                                disabledReason={refreshDisabledReason}
                                fullWidth
                            >
                                {insight.last_refresh ? (
                                    <div className="block my-1">
                                        Refresh data
                                        <p className="text-xs text-muted mt-0.5">
                                            Last computed{' '}
                                            <TZLabel
                                                time={insight.last_refresh}
                                                noStyles
                                                className="whitespace-nowrap border-dotted border-b"
                                            />
                                        </p>
                                    </div>
                                ) : (
                                    <>Refresh data</>
                                )}
                            </LemonButton>
                        )}
                    </>

                    {/* More */}
                    {moreButtons && (
                        <>
                            <LemonDivider />
                            {moreButtons}
                        </>
                    )}
                </>
            }
            moreTooltip={
                canEditInsight ? 'Rename, duplicate, export, refresh and more…' : 'Duplicate, export, refresh and more…'
            }
            extraControls={feedbackButtons}
        />
    )
}

export function InsightMetaContent({
    title,
    fallbackTitle,
    description,
    link,
    loading,
    loadingQueued,
    tags,
    query,
}: {
    title: string
    fallbackTitle?: string
    description?: string
    link?: string
    loading?: boolean
    loadingQueued?: boolean
    tags?: string[]
    query?: QueryBasedInsightModel['query']
}): JSX.Element {
    let titleEl: JSX.Element = (
        <h4 title={title} data-attr="insight-card-title">
            {title || <i>{fallbackTitle || 'Untitled'}</i>}
            {(loading || loadingQueued) && (
                <Tooltip
                    title={loading ? 'This insight is loading results.' : 'This insight is waiting to load results.'}
                    placement="top-end"
                >
                    <span className={clsx('text-sm font-medium ml-1.5', loading ? 'text-accent' : 'text-muted')}>
                        <Spinner className="mr-1.5 text-base" textColored />
                        {loading ? 'Loading' : 'Waiting to load'}
                    </span>
                </Tooltip>
            )}
        </h4>
    )
    if (link) {
        titleEl = <Link to={link}>{titleEl}</Link>
    }

    return (
        <>
            {titleEl}
            <div className="self-stretch">
                <DataWarehouseSyncNotice query={query} />
            </div>
            {!!description && (
                <LemonMarkdown className="CardMeta__description" lowKeyHeadings>
                    {description}
                </LemonMarkdown>
            )}
            {tags && tags.length > 0 && <ObjectTags tags={tags} staticOnly />}
            <LemonTableLoader loading={loading} />
        </>
    )
}
