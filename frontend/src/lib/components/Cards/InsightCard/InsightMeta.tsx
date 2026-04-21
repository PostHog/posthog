import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React, { useCallback, useEffect, useRef, useState } from 'react'

import { IconInfo, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

import { areAlertsSupportedForInsight, insightAlertsLogic } from 'lib/components/Alerts/insightAlertsLogic'
import { ManageAlertsModal } from 'lib/components/Alerts/views/ManageAlertsModal'
import { CardMeta } from 'lib/components/Cards/CardMeta'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { ExportButton } from 'lib/components/ExportButton/ExportButton'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { Link } from 'lib/lemon-ui/Link'
import { Popover } from 'lib/lemon-ui/Popover'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Splotch, SplotchColor } from 'lib/lemon-ui/Splotch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { getOverrideWarningPropsForButton } from 'scenes/insights/utils'
import { SurveyOpportunityButton } from 'scenes/surveys/components/SurveyOpportunityButton'
import { SURVEY_CREATED_SOURCE } from 'scenes/surveys/constants'
import { isSurveyableFunnelInsight } from 'scenes/surveys/utils/opportunityDetection'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { ProductKey } from '~/queries/schema/schema-general'
import { isDataVisualizationNode } from '~/queries/utils'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DashboardPlacement,
    DashboardTile,
    ExporterFormat,
    InsightColor,
    InsightLogicProps,
    InsightShortId,
    QueryBasedInsightModel,
} from '~/types'

import { DashboardInsightActions } from './DashboardInsightActions'
import { dashboardWidgetMenusLogic } from './dashboardWidgetMenusLogic'
import { DashboardWidgetPlacementMenus } from './DashboardWidgetPlacementMenus'
import { InsightCardProps } from './InsightCard'
import { InsightDetails } from './InsightDetails'

interface InsightMetaProps extends Pick<
    InsightCardProps,
    | 'ribbonColor'
    | 'updateColor'
    | 'toggleShowDescription'
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
    | 'copyToDashboard'
    | 'showEditingControls'
    | 'showDetailsControls'
    | 'moreButtons'
    | 'filtersOverride'
    | 'variablesOverride'
    | 'placement'
    | 'surveyOpportunity'
> {
    /** Called when the user mousedowns on the card meta (drag handle) in view mode to enter edit mode. */
    onDragHandleMouseDown?: React.MouseEventHandler<HTMLDivElement>
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
    toggleShowDescription,
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
    copyToDashboard,
    areDetailsShown,
    setAreDetailsShown,
    showEditingControls = true,
    showDetailsControls = true,
    moreButtons,
    placement,
    surveyOpportunity,
    onDragHandleMouseDown,
}: InsightMetaProps): JSX.Element {
    const { short_id, name, next_allowed_client_refresh: nextAllowedClientRefresh } = insight
    const tileFiltersOverride = tile?.filters_overrides
    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: insight.short_id,
        dashboardId,
        cachedInsight: insight,
        filtersOverride: filtersOverride ?? null,
        variablesOverride: variablesOverride ?? null,
        tileFiltersOverride: tileFiltersOverride ?? null,
    }
    const { insightFeedback, canToggleDisplayLabelsForInsight, canToggleLegendForInsight } = useValues(
        insightLogic(insightLogicProps)
    )
    const { setInsightFeedback } = useActions(insightLogic(insightLogicProps))
    const { exportContext, insightData, query } = useValues(insightDataLogic(insightLogicProps))
    const [isManageAlertsModalOpen, setIsManageAlertsModalOpen] = useState(false)
    const { loadAlerts: loadDeferredInsightAlerts } = useActions(
        insightAlertsLogic({
            insightId: insight.id ?? 0,
            insightLogicProps,
            deferInitialAlertsLoad: true,
        })
    )
    const { samplingFactor, hasDataWarehouseSeries } = useValues(insightVizDataLogic(insightLogicProps))
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const { copyToDestinations } = useValues(
        dashboardWidgetMenusLogic({
            instanceKey: insight.short_id,
            dashboardId,
            dashboards: insight.dashboards,
            dashboard_tiles: insight.dashboard_tiles,
        })
    )
    const { updateInsightDirect } = useActions(insightsModel)
    const { reportDashboardInsightMetaUpdated } = useActions(eventUsageLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const showCompactTile =
        placement === DashboardPlacement.Dashboard ||
        placement === DashboardPlacement.ProjectHomepage ||
        placement === DashboardPlacement.Public
    const isUsedAsDashboardTile =
        placement === DashboardPlacement.Dashboard ||
        placement === DashboardPlacement.Public ||
        placement === DashboardPlacement.Builtin
    const isSqlInsight = isDataVisualizationNode(insight.query)
    const showCompactHeading = !showCompactTile || (!filtersOverride?.date_from && !isSqlInsight)

    const topHeadingProps = {
        query: insight.query,
        lastRefresh: insight.last_refresh,
        hasTileOverrides: Object.keys(tileFiltersOverride ?? {}).length > 0,
        resolvedDateRange: insightData?.resolved_date_range,
    }

    const summary = useSummarizeInsight()(insight.query)

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

    const showDashboardAlertsMenuItem = isUsedAsDashboardTile && !!dashboardId && !!insight.id && canViewInsight
    const canCreateAlertForInsight = areAlertsSupportedForInsight(query)

    const canToggleDisplayLabels = isUsedAsDashboardTile && canEditInsight && canToggleDisplayLabelsForInsight
    const canToggleLegend = isUsedAsDashboardTile && canEditInsight && canToggleLegendForInsight

    const hasTileStyleActions = !!(showCompactTile && toggleShowDescription && insight.description) || !!updateColor
    const canShowCopyToDashboardTile = showCompactTile && !!copyToDashboard && canViewInsight
    const hasDashboardPlacementActions = canShowCopyToDashboardTile || !!moveToDashboard || !!removeFromDashboard

    // For dashboard-specific actions (remove from dashboard, change tile color), check dashboard permissions
    const currentDashboard = dashboardId ? nameSortedDashboards.find((d) => d.id === dashboardId) : null
    const canEditDashboard = currentDashboard?.user_access_level
        ? accessLevelSatisfied(
              AccessControlResourceType.Dashboard,
              currentDashboard.user_access_level,
              AccessControlLevel.Editor
          )
        : true

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

    const surveyOpportunityButton =
        surveyOpportunity && isSurveyableFunnelInsight(insight) ? (
            <SurveyOpportunityButton
                insight={insight}
                disableAutoPromptSubmit={true}
                source={SURVEY_CREATED_SOURCE.INSIGHT_CROSS_SELL}
                fromProduct={ProductKey.PRODUCT_ANALYTICS}
                tooltip="Create a survey to understand why users are dropping off"
            />
        ) : null

    // If user can't view the insight, show minimal interface
    if (!canViewInsight) {
        return (
            <CardMeta
                compact={showCompactTile}
                ribbonColor={ribbonColor}
                showEditingControls={false}
                showDetailsControls={false}
                setAreDetailsShown={setAreDetailsShown}
                areDetailsShown={areDetailsShown}
                detailsTooltip="Show insight details, such as creator, last edit, and applied filters."
                topHeading={null}
                onMouseDown={onDragHandleMouseDown}
                content={
                    <InsightMetaContent
                        link={undefined}
                        title="Access denied"
                        fallbackTitle={summary}
                        description={undefined}
                        loading={loading}
                        loadingQueued={loadingQueued}
                        tags={[]}
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

    const topHeadingEl = showCompactHeading ? (
        <TopHeading {...topHeadingProps} showInsightType={!showCompactTile} />
    ) : null
    const popoverTopHeadingEl = showCompactTile ? <TopHeading {...topHeadingProps} /> : undefined

    const metaDescriptionEl =
        insight.description && tile?.show_description === false ? (
            <LemonMarkdown className="text-xs" lowKeyHeadings>
                {insight.description}
            </LemonMarkdown>
        ) : null

    const metaDetailsEl = showDetailsControls ? (
        <InsightDetails
            query={insight.query}
            footerInfo={insight}
            variablesOverride={variablesOverride}
            filtersOverride={filtersOverride}
            tileFiltersOverride={tileFiltersOverride ?? null}
            hasDataWarehouseSeries={hasDataWarehouseSeries}
        />
    ) : null

    const onMetaSave = canEditInsight
        ? (updates: { name?: string; description?: string }) => {
              updateInsightDirect(insight, updates)
              if (updates.description && !tile?.show_description && toggleShowDescription) {
                  toggleShowDescription()
              }
              const attribute = updates.name !== undefined ? 'name' : 'description'
              reportDashboardInsightMetaUpdated(dashboardId, insight.id, attribute)
          }
        : undefined

    return (
        <>
            <CardMeta
                compact={showCompactTile}
                ribbonColor={ribbonColor}
                showEditingControls={showEditingControls}
                showDetailsControls={showDetailsControls}
                setAreDetailsShown={setAreDetailsShown}
                areDetailsShown={areDetailsShown}
                detailsTooltip="Show insight details, such as creator, last edit, and applied filters."
                onMouseDown={onDragHandleMouseDown}
                topHeading={topHeadingEl}
                popoverTopHeading={popoverTopHeadingEl}
                content={
                    <InsightMetaContent
                        link={urls.insightView(
                            short_id,
                            dashboardId,
                            variablesOverride,
                            filtersOverride,
                            tileFiltersOverride
                        )}
                        title={name}
                        fallbackTitle={summary}
                        description={insight.description}
                        loading={loading}
                        loadingQueued={loadingQueued}
                        tags={insight.tags}
                        compact={showCompactTile}
                        showDescription={tile?.show_description !== false}
                        infoPopover={
                            showCompactTile ? (
                                <CompactInfoPopover
                                    popoverTopHeading={popoverTopHeadingEl ?? topHeadingEl}
                                    metaTitle={name}
                                    metaDescription={metaDescriptionEl}
                                    metaDescriptionText={insight.description || ''}
                                    onMetaSave={onMetaSave}
                                    metaDetails={metaDetailsEl}
                                />
                            ) : null
                        }
                    />
                }
                metaTitle={name}
                metaDescription={metaDescriptionEl}
                metaDescriptionText={insight.description || ''}
                onMetaSave={onMetaSave}
                metaDetails={metaDetailsEl}
                samplingFactor={samplingFactor}
                moreButtons={
                    <>
                        {/* Insight related */}
                        {canViewInsight && (
                            <LemonButton
                                to={urls.insightView(
                                    short_id,
                                    dashboardId,
                                    variablesOverride,
                                    filtersOverride,
                                    tileFiltersOverride
                                )}
                                fullWidth
                            >
                                View
                            </LemonButton>
                        )}
                        {canEditInsight && (
                            <>
                                <LemonButton
                                    to={
                                        isDataVisualizationNode(insight.query)
                                            ? urls.sqlEditor({
                                                  insightShortId: short_id,
                                                  dashboard: dashboardId ?? undefined,
                                              })
                                            : urls.insightEdit(short_id, dashboardId)
                                    }
                                    fullWidth
                                    {...getOverrideWarningPropsForButton(filtersOverride, variablesOverride)}
                                >
                                    Edit
                                </LemonButton>
                                <LemonButton onClick={rename} fullWidth>
                                    Rename
                                </LemonButton>
                                {tile && (
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
                                dashboardId
                                    ? 'duplicate-insight-from-dashboard'
                                    : 'duplicate-insight-from-card-list-view'
                            }
                        >
                            Duplicate
                        </LemonButton>
                        {showDashboardAlertsMenuItem && insight.id ? (
                            <LemonButton
                                onClick={() => {
                                    void loadDeferredInsightAlerts()
                                    setIsManageAlertsModalOpen(true)
                                }}
                                fullWidth
                                data-attr="dashboard-insight-manage-alerts"
                            >
                                Alerts
                            </LemonButton>
                        ) : null}
                        <DashboardInsightActions
                            insight={insight}
                            insightLogicProps={insightLogicProps}
                            dashboardId={dashboardId}
                            canToggleDisplayLabels={canToggleDisplayLabels}
                            canToggleLegend={canToggleLegend}
                        />

                        {canShowCopyToDashboardTile && !canEditDashboard && (
                            <>
                                {!canToggleDisplayLabels && <LemonDivider />}
                                <h5 className="mx-2 my-1">Dashboard</h5>
                                <DashboardWidgetPlacementMenus
                                    placementDestinations={copyToDestinations}
                                    onCopyToDashboard={copyToDashboard}
                                />
                            </>
                        )}

                        {/* Dashboard related */}
                        {canEditDashboard && (
                            <>
                                {!canToggleDisplayLabels && !canToggleLegend && <LemonDivider />}
                                {showCompactTile && toggleShowDescription && !!insight.description && (
                                    <LemonButton onClick={toggleShowDescription} fullWidth>
                                        {tile?.show_description === false ? 'Show description' : 'Hide description'}
                                    </LemonButton>
                                )}
                                {updateColor && (
                                    <LemonMenu
                                        items={Object.values(InsightColor).map((availableColor) => ({
                                            label: (
                                                <span className="flex items-center gap-2">
                                                    {availableColor !== InsightColor.White ? (
                                                        <Splotch color={availableColor as string as SplotchColor} />
                                                    ) : null}
                                                    <span>
                                                        {availableColor !== InsightColor.White
                                                            ? capitalizeFirstLetter(availableColor)
                                                            : 'No color'}
                                                    </span>
                                                </span>
                                            ),
                                            key: availableColor,
                                            active: availableColor === (ribbonColor || InsightColor.White),
                                            onClick: () => {
                                                updateColor?.(availableColor)
                                            },
                                        }))}
                                        placement="right-start"
                                        fallbackPlacements={['left-start']}
                                        closeParentPopoverOnClickInside
                                    >
                                        <LemonButton fullWidth>Set color</LemonButton>
                                    </LemonMenu>
                                )}
                                {hasDashboardPlacementActions && (
                                    <>
                                        {hasTileStyleActions && <LemonDivider />}
                                        <h5 className="mx-2 my-1">Dashboard</h5>
                                        <DashboardWidgetPlacementMenus
                                            placementDestinations={copyToDestinations}
                                            onMoveToDashboard={moveToDashboard}
                                            onCopyToDashboard={canShowCopyToDashboardTile ? copyToDashboard : undefined}
                                        />
                                        {removeFromDashboard && (
                                            <LemonButton
                                                status="danger"
                                                onClick={() =>
                                                    LemonDialog.open({
                                                        title: 'Remove from dashboard',
                                                        description:
                                                            'Are you sure you want to remove this insight from the dashboard?',
                                                        primaryButton: {
                                                            children: 'Remove from dashboard',
                                                            status: 'danger',
                                                            onClick: removeFromDashboard,
                                                        },
                                                        secondaryButton: {
                                                            children: 'Cancel',
                                                        },
                                                    })
                                                }
                                                fullWidth
                                            >
                                                Remove from dashboard
                                            </LemonButton>
                                        )}
                                    </>
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
                                            dashboard: insightLogicProps.dashboardId,
                                            export_context: exportContext,
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
                    canEditInsight
                        ? 'Rename, duplicate, export, refresh and more…'
                        : 'Duplicate, export, refresh and more…'
                }
                extraControls={surveyOpportunityButton ?? feedbackButtons}
            />
            {showDashboardAlertsMenuItem && insight.id ? (
                <ManageAlertsModal
                    isOpen={isManageAlertsModalOpen}
                    onClose={() => setIsManageAlertsModalOpen(false)}
                    insightLogicProps={insightLogicProps}
                    insightId={insight.id}
                    insightShortId={short_id as InsightShortId}
                    canCreateAlertForInsight={canCreateAlertForInsight}
                    deferInitialAlertsLoad
                />
            ) : null}
        </>
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
    compact,
    showDescription,
    infoPopover,
}: {
    title: string
    fallbackTitle?: string
    description?: string
    link?: string
    loading?: boolean
    loadingQueued?: boolean
    tags?: string[]
    compact?: boolean
    showDescription?: boolean
    infoPopover?: JSX.Element | null
}): JSX.Element {
    const titleContent = (
        <>
            <span className={clsx(infoPopover && 'truncate text-primary')}>
                {title || <i>{fallbackTitle || 'Untitled'}</i>}
            </span>
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
        </>
    )

    const titleEl = (
        <h4
            title={!compact ? title : undefined}
            data-attr="insight-card-title"
            className={clsx(infoPopover && 'inline-flex items-center overflow-visible')}
        >
            {link ? (
                <Link to={link} className="max-w-full truncate">
                    {titleContent}
                </Link>
            ) : (
                titleContent
            )}
            {infoPopover}
        </h4>
    )

    return (
        <>
            {titleEl}
            {(!compact || showDescription) && !!description && (
                <LemonMarkdown className="CardMeta__description" lowKeyHeadings>
                    {description}
                </LemonMarkdown>
            )}
            {!compact && tags && tags.length > 0 && <ObjectTags tags={tags} staticOnly />}
            <LemonTableLoader loading={loading} />
        </>
    )
}

function CompactInfoPopover({
    popoverTopHeading,
    metaTitle,
    metaDescription,
    metaDescriptionText,
    onMetaSave,
    metaDetails,
}: {
    popoverTopHeading?: JSX.Element | null
    metaTitle: string
    metaDescription?: JSX.Element | null
    metaDescriptionText: string
    onMetaSave?: (updates: { name?: string; description?: string }) => void
    metaDetails?: JSX.Element | null
}): JSX.Element {
    const [popoverVisible, setPopoverVisible] = useState(false)
    const [pinned, setPinned] = useState(false)
    const hoverTimerRef = useRef<ReturnType<typeof setTimeout>>()

    useEffect(() => () => clearTimeout(hoverTimerRef.current), [])

    const clearHoverTimer = (): void => clearTimeout(hoverTimerRef.current)

    const showDetails = useCallback(() => {
        clearHoverTimer()
        hoverTimerRef.current = setTimeout(() => setPopoverVisible(true), 300)
    }, [])

    const hideDetails = useCallback(() => {
        clearHoverTimer()
        hoverTimerRef.current = setTimeout(() => setPopoverVisible(false), 800)
    }, [])

    const handleClickInfo = useCallback(
        (e: React.MouseEvent) => {
            e.preventDefault()
            e.stopPropagation()
            clearHoverTimer()
            const newPinned = !pinned
            setPinned(newPinned)
            setPopoverVisible(newPinned)
        },
        [pinned]
    )

    const handleClickOutside = useCallback(() => {
        clearHoverTimer()
        setPinned(false)
        setPopoverVisible(false)
    }, [])

    return (
        <Popover
            visible={popoverVisible}
            placement="bottom"
            showArrow
            onClickOutside={handleClickOutside}
            onMouseEnterInside={showDetails}
            onMouseLeaveInside={pinned ? undefined : hideDetails}
            overlay={
                <div
                    className="p-4 max-w-md space-y-3"
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                    }}
                >
                    {popoverTopHeading && (
                        <h5 className="uppercase text-xs font-bold text-muted tracking-wide m-0">
                            {popoverTopHeading}
                        </h5>
                    )}
                    {onMetaSave ? (
                        <>
                            <EditableField
                                name="title"
                                value={metaTitle || ''}
                                onSave={(value) => onMetaSave({ name: value })}
                                placeholder="Untitled"
                                saveOnBlur
                                clickToEdit
                                compactButtons
                                compactIcon
                                className="font-semibold text-sm mt-1"
                                data-attr="insight-card-title"
                            />
                            <EditableField
                                name="description"
                                value={metaDescriptionText || ''}
                                onSave={(value) => onMetaSave({ description: value })}
                                placeholder="Enter description (optional)"
                                saveOnBlur
                                clickToEdit
                                multiline
                                markdown
                                compactButtons
                                compactIcon
                                className="text-xs w-full"
                                data-attr="insight-card-description"
                            />
                        </>
                    ) : (
                        <>
                            {metaTitle && <p className="font-semibold m-0">{metaTitle}</p>}
                            {metaDescription}
                        </>
                    )}
                    {metaDetails}
                </div>
            }
        >
            <span
                className="ml-1 flex-shrink-0"
                onMouseEnter={showDetails}
                onMouseLeave={pinned ? undefined : hideDetails}
            >
                <LemonButton
                    icon={<IconInfo />}
                    size="small"
                    noPadding
                    data-attr="card-meta-info"
                    onClick={handleClickInfo}
                />
            </span>
        </Popover>
    )
}
