import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React, { useMemo, useState } from 'react'

import { IconClock, IconPulse, IconThumbsDown, IconThumbsUp, IconWarning } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

import { CardMeta } from 'lib/components/Cards/CardMeta'
import { CardMetaRefreshButton } from 'lib/components/Cards/CardMetaRefreshButton'
import { CompactInfoPopover } from 'lib/components/Cards/InsightCard/CompactInfoPopover'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import type { DisplayOptionTab } from 'lib/components/ChartOptions/displayOptions'
import { useDisplayOptions } from 'lib/components/ChartOptions/useDisplayOptions'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { captureImageLogic } from 'lib/components/Scenes/InsightOrDashboard/captureImageLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { reportDashboardInsightMetaUpdated } from 'scenes/dashboard/dashboardEvents'
import { getEffectiveDateOverride } from 'scenes/dashboard/dashboardUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { getOverrideWarningPropsForButton } from 'scenes/insights/utils'
import { SurveyOpportunityButton } from 'scenes/surveys/components/SurveyOpportunityButton'
import { SURVEY_CREATED_SOURCE } from 'scenes/surveys/constants'
import { isSurveyableFunnelInsight, SurveyableFunnelInsight } from 'scenes/surveys/utils/opportunityDetection'
import { urls } from 'scenes/urls'

import { insightsModel } from '~/models/insightsModel'
import { queryScanHasActionableFinding } from '~/queries/nodes/DataNode/queryScan'
import { QueryScanTileTooltip } from '~/queries/nodes/DataNode/QueryScanTileTooltip'
import { WarehouseSyncWarningList } from '~/queries/nodes/DataNode/WarehouseSyncWarningList'
import { outOfDateSyncWarnings } from '~/queries/nodes/DataNode/warehouseSyncWarnings'
import { copyTableData, getInsightExportAdapter } from '~/queries/nodes/InsightViz/exportAdapters'
import {
    isDataVisualizationNode,
    isDataVisualizationNodeWithHogQLQuery,
    isInsightVizNode,
    isTrendsQuery,
} from '~/queries/schema/node-guards'
import { Node, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DashboardPlacement,
    DashboardTile,
    ExporterFormat,
    InsightColor,
    InsightLogicProps,
    InsightShortId,
    InsightModel,
} from '~/types'

import {
    areAlertsSupportedForInsight,
    areAnomalyAlertsSupportedForInsight,
    insightAlertsLogic,
} from 'products/alerts/frontend/logic/insightAlertsLogic'
import type { AlertType } from 'products/alerts/frontend/types'
import { ManageAlertsModal } from 'products/alerts/frontend/views/ManageAlertsModal'
import { dataRetentionBannerLogic } from 'products/product_analytics/frontend/insights/dataRetention/dataRetentionBannerLogic'
import { exceedsRetention } from 'products/product_analytics/frontend/insights/dataRetention/exceedsRetention'
import { insightDisplayOptions } from 'products/product_analytics/frontend/insights/editor/insightDisplayOptions'

import { useDashboardVisualizationOptions } from './dashboardVisualizationOptions'
import type { DashboardVisualizationPersistence } from './dashboardVisualizationOptions'
import { dashboardWidgetMenusLogic } from './dashboardWidgetMenusLogic'
import { InsightCardProps } from './InsightCard'
import { insightCardCaptureTarget } from './insightCardImageCapture'
import type { InsightCardMenu } from './insightCardMenu'
import { InsightCardMoreButtons } from './InsightCardMoreButtons'
import { InsightDetails } from './InsightDetails'

interface InsightMetaProps extends Pick<
    InsightCardProps,
    | 'ribbonColor'
    | 'updateColor'
    | 'toggleShowDescription'
    | 'removeFromDashboard'
    | 'deleteWithUndo'
    | 'refresh'
    | 'refreshAfterDisplayOptionsChange'
    | 'loading'
    | 'loadingQueued'
    | 'rename'
    | 'setOverride'
    | 'duplicate'
    | 'dashboardId'
    | 'canEditDashboard'
    | 'moveToDashboard'
    | 'tileGroupMoveOptions'
    | 'moveToTileGroup'
    | 'copyToDashboard'
    | 'showEditingControls'
    | 'showDetailsControls'
    | 'moreButtons'
    | 'filtersOverride'
    | 'variablesOverride'
    | 'placement'
    | 'surveyOpportunity'
    | 'showCreateAnomalyAlertButton'
    | 'projectId'
    | 'contextHeading'
> {
    /** Called when the user mousedowns on the card meta (drag handle) in view mode to enter edit mode. */
    onDragHandleMouseDown?: React.MouseEventHandler<HTMLDivElement>
    tile?: DashboardTile
    headerStatus?: JSX.Element
    insight: InsightModel
    refreshDisabledReason?: string
    areDetailsShown?: boolean
    setAreDetailsShown?: React.Dispatch<React.SetStateAction<boolean>>
    onInfoVisibilityChange?: (visible: boolean) => void
    persistDisplayOptions?: (node: Node) => void
    onCreateAlert?: () => void
    onEditAlert?: (alertId: AlertType['id']) => void
    onCreateAnomalyAlert?: () => void
}

const NO_DISPLAY_OPTION_TABS: DisplayOptionTab[] = []

// SQL tiles have no display option tabs, so they skip the hook and the insight logics it mounts.
export function InsightMeta(props: InsightMetaProps): JSX.Element {
    return isDataVisualizationNode(props.insight.query) ? (
        <InsightMetaBody {...props} displayOptionTabs={NO_DISPLAY_OPTION_TABS} />
    ) : (
        <InsightMetaWithDisplayOptions {...props} />
    )
}

function InsightMetaWithDisplayOptions(props: InsightMetaProps): JSX.Element {
    // Hoist the hooks out of the More overlay so kea logics they mount don't do so lazily inside a
    // portal, which cascades into closing the dropdown before the user can interact with it.
    const { tabs } = useDisplayOptions(insightDisplayOptions)
    return <InsightMetaBody {...props} displayOptionTabs={tabs} />
}

function InsightMetaBody({
    displayOptionTabs,
    headerStatus,
    tile,
    insight,
    ribbonColor,
    dashboardId,
    canEditDashboard,
    updateColor,
    toggleShowDescription,
    filtersOverride,
    variablesOverride,
    removeFromDashboard,
    deleteWithUndo,
    refresh,
    refreshDisabledReason: capacityDisabledReason,
    refreshAfterDisplayOptionsChange,
    loading,
    loadingQueued,
    rename,
    duplicate,
    setOverride,
    moveToDashboard,
    tileGroupMoveOptions,
    moveToTileGroup,
    copyToDashboard,
    areDetailsShown,
    setAreDetailsShown,
    onInfoVisibilityChange,
    showEditingControls = true,
    showDetailsControls = true,
    moreButtons,
    placement,
    surveyOpportunity,
    showCreateAnomalyAlertButton,
    onDragHandleMouseDown,
    persistDisplayOptions,
    onCreateAlert,
    onEditAlert,
    onCreateAnomalyAlert,
    projectId,
    contextHeading,
}: InsightMetaProps & { displayOptionTabs: DisplayOptionTab[] }): JSX.Element {
    const { short_id, name, next_allowed_client_refresh: nextAllowedClientRefresh } = insight
    const tileFiltersOverride = tile?.filters_overrides
    const insightLogicProps: InsightLogicProps = {
        dashboardItemId: insight.short_id,
        dashboardId,
        cachedInsight: insight,
        filtersOverride: filtersOverride ?? null,
        variablesOverride: variablesOverride ?? null,
        tileFiltersOverride: tileFiltersOverride ?? null,
        setQuery: persistDisplayOptions,
        refreshAfterDisplayOptionsChange,
    }
    const { insightFeedback } = useValues(insightLogic(insightLogicProps))
    const { setInsightFeedback } = useActions(insightLogic(insightLogicProps))
    const {
        exportContext,
        insightData,
        insightDataRaw,
        query,
        savingDisplayOptions,
        savingSqlVisualization,
        sqlVisualizationVersion,
    } = useValues(insightDataLogic(insightLogicProps))
    const { persistSqlVisualization } = useActions(insightDataLogic(insightLogicProps))
    const [isManageAlertsModalOpen, setIsManageAlertsModalOpen] = useState(false)
    const { loadAlerts: loadDeferredInsightAlerts } = useActions(
        insightAlertsLogic({
            insightId: insight.id ?? 0,
            insightLogicProps,
            deferInitialAlertsLoad: true,
        })
    )
    const { samplingFactor, hasDataWarehouseSeries } = useValues(insightVizDataLogic(insightLogicProps))
    const { retentionApplies, retentionMonths, retentionPeriodLabel } = useValues(dataRetentionBannerLogic)
    const dashboardWidgetMenusLogicProps = {
        instanceKey: insight.short_id,
        dashboardId,
        dashboard_tiles: insight.dashboard_tiles,
    }
    const { copyToDestinations } = useValues(dashboardWidgetMenusLogic(dashboardWidgetMenusLogicProps))
    const { copyImage } = useActions(captureImageLogic)
    const { isCapturing: isCapturingImage } = useValues(captureImageLogic)
    const { updateInsightDirect } = useActions(insightsModel)
    const { reportInsightResultsCopiedToClipboard } = useActions(eventUsageLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const showCompactTile =
        placement === DashboardPlacement.Dashboard ||
        placement === DashboardPlacement.ProjectHomepage ||
        placement === DashboardPlacement.Public
    const isUsedAsDashboardTile =
        placement === DashboardPlacement.Dashboard ||
        placement === DashboardPlacement.Public ||
        placement === DashboardPlacement.Builtin
    const isSqlInsight = isDataVisualizationNodeWithHogQLQuery(insight.query)
    const showCompactHeading = !showCompactTile || !isSqlInsight

    const ignoresDashboardFilters = !!tileFiltersOverride?.ignoreDashboardFilters
    // The ignore flag is surfaced by its own notice, so it alone shouldn't trigger the overrides warning.
    const hasTileOverrides = Object.keys(tileFiltersOverride ?? {}).some((key) => key !== 'ignoreDashboardFilters')
    const dateOverride = getEffectiveDateOverride(insight.filter_override_context, filtersOverride, tileFiltersOverride)
    const showsDataRetentionWarning =
        retentionApplies &&
        placement !== DashboardPlacement.Public &&
        placement !== DashboardPlacement.Export &&
        exceedsRetention({
            query: insight.query,
            dateFromOverride: dateOverride.dateFromOverride,
            resolvedDateFrom: insightData?.resolved_date_range?.date_from,
            retentionMonths,
        })
    const dataRetentionWarning =
        showsDataRetentionWarning && retentionPeriodLabel
            ? `This insight's date range goes beyond your ${retentionPeriodLabel} data retention, so events older than that aren't included.`
            : null
    const topHeadingProps = {
        query: insight.query,
        lastRefresh: insight.last_refresh,
        hasTileOverrides,
        ignoresDashboardFilters,
        resolvedDateRange: insightData?.resolved_date_range,
        ...dateOverride,
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

    // A killed run has no result to carry the scan, so it arrives on the query status instead.
    const queryScan: InsightModel['query_scan'] = insight.query_scan ?? insight.query_status?.query_scan
    const scanFindings = queryScan?.analysis?.findings ?? []
    const queryScanTooltip =
        canEditInsight && queryScan && scanFindings.length > 0 ? (
            <QueryScanTileTooltip summary={queryScan} findings={scanFindings} />
        ) : null
    const syncWarnings = outOfDateSyncWarnings(insight.warnings)
    const warehouseSyncTooltip =
        syncWarnings.length > 0 ? (
            <div className="flex flex-col gap-1">
                <span>
                    Some warehouse tables this insight reads are out of date, so its results may not be current:
                </span>
                <WarehouseSyncWarningList warnings={syncWarnings} />
            </div>
        ) : null

    const showDashboardAlertsMenuItem = isUsedAsDashboardTile && !!dashboardId && !!insight.id && canViewInsight
    const alertSupportOptions = { metricsAlertsEnabled: !!featureFlags[FEATURE_FLAGS.METRICS] }
    const canCreateAlertForInsight = areAlertsSupportedForInsight(query, alertSupportOptions)
    const canCreateAnomalyAlertForInsight = areAnomalyAlertsSupportedForInsight(query, alertSupportOptions)

    const showCopyTableData = isInsightVizNode(query) && isTrendsQuery(query.source)
    const copyTableAdapter = useMemo(() => getInsightExportAdapter(insightDataRaw, query), [insightDataRaw, query])

    const showDisplayOptionsMenu = isUsedAsDashboardTile && canEditInsight && !!persistDisplayOptions
    const dashboardVisualizationPersistence: DashboardVisualizationPersistence | undefined = persistDisplayOptions
        ? {
              saving: savingSqlVisualization,
              version: sqlVisualizationVersion,
              persistChartType: (display) => persistSqlVisualization({ type: 'chart-type', display }),
              persistDisplayOptions: (sqlQuery) =>
                  persistSqlVisualization({ type: 'display-options', query: sqlQuery }),
          }
        : undefined
    const visualizationItems = useDashboardVisualizationOptions({
        query,
        insightData,
        variablesOverride,
        loading: loading || loadingQueued,
        persistence: dashboardVisualizationPersistence,
        savingDisplayOptions,
    })

    const canShowCopyToDashboardTile = showCompactTile && !!copyToDashboard && canViewInsight
    const hasDashboardPlacementActions = canShowCopyToDashboardTile || !!moveToDashboard || !!removeFromDashboard

    const canEditCurrentDashboard = canEditDashboard ?? !dashboardId

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

    const surveyOpportunityInsight = surveyOpportunity && isSurveyableFunnelInsight(insight) ? insight : null
    const canShowCreateAnomalyAlert =
        showCreateAnomalyAlertButton &&
        canViewInsight &&
        canCreateAnomalyAlertForInsight &&
        !!short_id &&
        !!insight.id &&
        !!onCreateAnomalyAlert

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

    // Suppress this tile's icon only while this tile itself is refreshing (a full-dashboard
    // refresh marks every tile as loading, so it still hides them all). Other tiles stay
    // refreshable — the batched refresh already caps concurrency, so there's no need to block.
    const tileRefreshing = !!(loading || loadingQueued)
    const nextRefreshFromNow =
        nextAllowedClientRefresh && dayjs(nextAllowedClientRefresh).isAfter(dayjs())
            ? dayjs(nextAllowedClientRefresh).fromNow()
            : null
    const refreshDisabledReason =
        capacityDisabledReason ??
        (nextRefreshFromNow
            ? `These results are already up to date. The next refresh is available ${nextRefreshFromNow}.`
            : undefined)
    // The always-visible "⋯" menu keeps refresh reachable on touch/keyboard. Unlike the hover
    // icon (which hides while this tile refreshes) the menu item stays but disables.
    const refreshMenuDisabledReason = tileRefreshing ? 'Refreshing…' : refreshDisabledReason

    // A browser capture takes whatever is on screen, so a tile captured mid-load makes a valid PNG of an
    // empty card.
    const copyImageDisabledReason = isCapturingImage
        ? 'Copying…'
        : tileRefreshing
          ? 'Wait for the insight to finish loading'
          : undefined

    // Gate the hover icon on `showEditingControls` so it doesn't appear on public/export
    // dashboards, matching the "⋯" menu (which is already gated there).
    const refreshControl =
        refresh && showEditingControls && !tileRefreshing ? (
            <CardMetaRefreshButton
                onRefresh={() => refresh()}
                lastRefresh={insight.last_refresh}
                disabledReason={refreshDisabledReason}
                dataAttr="insight-card-refresh"
            />
        ) : null

    // On compact dashboard tiles the date just mirrors the dashboard's own range unless the
    // tile overrides it, so suppress the redundant label and only keep it for tile-level overrides.
    const tileHasOwnDateOverride = tileFiltersOverride?.date_from != null || tileFiltersOverride?.date_to != null
    const topHeadingEl = showCompactHeading ? (
        <TopHeading
            {...topHeadingProps}
            showInsightType={!showCompactTile}
            showDate={!showCompactTile || tileHasOwnDateOverride}
        />
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
            filterOverrideContext={insight.filter_override_context}
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

    // Carries the dashboard's filters and variables, so the link opens exactly what the tile shows
    // A card showing another project's insight must link into that project, not the current one.
    const inInsightProject = (path: string): string => (projectId ? urls.project(projectId, path) : path)
    const insightViewUrl = inInsightProject(
        urls.insightView(short_id, dashboardId, variablesOverride, filtersOverride, tileFiltersOverride)
    )
    const copyInsightLink = (): void => {
        void copyToClipboard(
            urls.absolute(projectId ? insightViewUrl : urls.currentProject(insightViewUrl)),
            'insight link'
        )
    }

    const placementActions = {
        destinations: copyToDestinations,
        onMoveToDashboard: moveToDashboard,
        tileGroupMoveOptions,
        onMoveToTileGroup: moveToTileGroup,
        onCopyToDashboard: canShowCopyToDashboardTile ? copyToDashboard : undefined,
    }
    const menu: InsightCardMenu = {
        view: canViewInsight
            ? {
                  url: insightViewUrl,
                  onCopyLink: copyInsightLink,
                  copyLinkDataAttr: dashboardId
                      ? 'copy-insight-link-from-dashboard'
                      : 'copy-insight-link-from-card-list-view',
              }
            : null,
        edit: canEditInsight
            ? {
                  url: inInsightProject(
                      isDataVisualizationNode(insight.query) && insight.query.kind !== NodeKind.BIVisualizationNode
                          ? urls.sqlEditor({ insightShortId: short_id, dashboard: dashboardId ?? undefined })
                          : urls.insightEdit(short_id, dashboardId)
                  ),
                  overrideWarning: getOverrideWarningPropsForButton(insight.query, filtersOverride, variablesOverride),
              }
            : null,
        rename: canEditInsight && rename ? rename : null,
        setOverride: canEditInsight && tile ? () => setOverride?.() : null,
        duplicate: duplicate
            ? {
                  onClick: duplicate,
                  dataAttr: dashboardId ? 'duplicate-insight-from-dashboard' : 'duplicate-insight-from-card-list-view',
              }
            : null,
        openAlerts:
            showDashboardAlertsMenuItem && insight.id
                ? () => {
                      void loadDeferredInsightAlerts()
                      setIsManageAlertsModalOpen(true)
                  }
                : null,
        displayOptions: showDisplayOptionsMenu ? { visualizationItems, tabs: displayOptionTabs } : null,
        viewerPlacement:
            canShowCopyToDashboardTile && !canEditCurrentDashboard
                ? { destinations: copyToDestinations, onCopyToDashboard: copyToDashboard }
                : null,
        dashboard: canEditCurrentDashboard
            ? {
                  description:
                      showCompactTile && toggleShowDescription && !!insight.description
                          ? { shown: tile?.show_description !== false, toggle: toggleShowDescription }
                          : null,
                  color: updateColor ? { current: ribbonColor || InsightColor.White, update: updateColor } : null,
                  placement: hasDashboardPlacementActions ? { ...placementActions, removeFromDashboard } : null,
              }
            : null,
        deleteInsight:
            canEditInsight && !removeFromDashboard && deleteWithUndo
                ? () => {
                      void (async () => {
                          try {
                              await deleteWithUndo()
                          } catch (error: any) {
                              lemonToast.error(`Failed to delete insight meta: ${error.detail}`)
                          }
                      })()
                  }
                : null,
        export: exportContext
            ? {
                  items: [
                      {
                          export_format: ExporterFormat.PNG,
                          insight: insight.id,
                          dashboard: insightLogicProps.dashboardId,
                          export_context: exportContext,
                      },
                      { export_format: ExporterFormat.CSV, export_context: exportContext },
                      { export_format: ExporterFormat.XLSX, export_context: exportContext },
                  ],
                  copyToClipboardItems: showCopyTableData
                      ? [
                            {
                                title: 'CSV',
                                onClick: () => {
                                    if (!copyTableAdapter) {
                                        return
                                    }
                                    copyTableData(copyTableAdapter.toTableData(), ExporterFormat.CSV)
                                    reportInsightResultsCopiedToClipboard(
                                        'csv',
                                        insight.id ?? null,
                                        dashboardId ?? null
                                    )
                                },
                                disabledReason: copyTableAdapter ? undefined : 'No data to copy yet',
                                'data-attr': 'insight-card-copy-as-csv',
                            },
                        ]
                      : undefined,
              }
            : null,
        copyImage: {
            onClick: () => copyImage(insightCardCaptureTarget(insight, tile, dashboardId)),
            disabledReason: copyImageDisabledReason,
        },
        refresh: refresh
            ? { onRefresh: refresh, disabledReason: refreshMenuDisabledReason, lastRefresh: insight.last_refresh }
            : null,
    }
    const menuTooltip = canEditInsight
        ? 'Rename, duplicate, export, copy as PNG, refresh and more…'
        : 'Duplicate, export, copy as PNG, refresh and more…'

    const metaContentProps: InsightMetaContentProps = {
        link: insightViewUrl,
        title: name,
        fallbackTitle: summary,
        description: insight.description,
        loading,
        loadingQueued,
        tags: insight.tags,
        compact: showCompactTile,
        showDescription: tile?.show_description !== false,
        dataRetentionWarning,
        queryScanTooltip,
        warehouseSyncTooltip,
        queryScanActionable: queryScanHasActionableFinding(scanFindings),
    }
    const infoPopoverProps = {
        onVisibilityChange: onInfoVisibilityChange,
        popoverTopHeading: popoverTopHeadingEl ?? topHeadingEl,
        metaTitle: name,
        metaDescription: metaDescriptionEl,
        metaDescriptionText: insight.description || '',
        onMetaSave,
        metaDetails: metaDetailsEl,
    }
    const topHeading = contextHeading ? (
        <span className="flex items-center gap-2 min-w-0">
            {contextHeading}
            {topHeadingEl}
        </span>
    ) : (
        topHeadingEl
    )
    const manageAlertsModal =
        showDashboardAlertsMenuItem && insight.id ? (
            <ManageAlertsModal
                isOpen={isManageAlertsModalOpen}
                onClose={() => setIsManageAlertsModalOpen(false)}
                insightLogicProps={insightLogicProps}
                insightId={insight.id}
                insightShortId={short_id as InsightShortId}
                canCreateAlertForInsight={canCreateAlertForInsight}
                onCreateAlert={onCreateAlert}
                onEditAlert={onEditAlert}
                insightQuery={query}
                deferInitialAlertsLoad
            />
        ) : null

    return (
        <>
            <CardMeta
                compact={showCompactTile}
                headerStatus={headerStatus}
                ribbonColor={ribbonColor}
                showEditingControls={showEditingControls}
                showDetailsControls={showDetailsControls}
                setAreDetailsShown={setAreDetailsShown}
                areDetailsShown={areDetailsShown}
                detailsTooltip="Show insight details, such as creator, last edit, and applied filters."
                onMouseDown={onDragHandleMouseDown}
                topHeading={topHeading}
                popoverTopHeading={popoverTopHeadingEl}
                content={
                    <InsightMetaContent
                        {...metaContentProps}
                        infoPopover={showCompactTile ? <CompactInfoPopover {...infoPopoverProps} /> : null}
                    />
                }
                metaTitle={name}
                metaDescription={metaDescriptionEl}
                metaDescriptionText={insight.description || ''}
                onMetaSave={onMetaSave}
                metaDetails={metaDetailsEl}
                samplingFactor={samplingFactor}
                moreButtons={<InsightCardMoreButtons menu={menu} moreButtons={moreButtons} />}
                moreTooltip={menuTooltip}
                extraControls={
                    placement !== DashboardPlacement.Public &&
                    (surveyOpportunityInsight || canShowCreateAnomalyAlert || feedbackButtons) ? (
                        <InsightMetaExtraControls
                            surveyOpportunityInsight={surveyOpportunityInsight}
                            onCreateAnomalyAlert={canShowCreateAnomalyAlert ? onCreateAnomalyAlert : undefined}
                            feedbackButtons={feedbackButtons}
                        />
                    ) : null
                }
                refreshControl={refreshControl}
            />
            {manageAlertsModal}
        </>
    )
}

interface InsightMetaExtraControlsProps {
    showLabel?: boolean
    surveyOpportunityInsight?: SurveyableFunnelInsight | null
    onCreateAnomalyAlert?: () => void
    feedbackButtons?: JSX.Element | null
}

function CreateAnomalyAlertButton({ onClick, showLabel }: { onClick: () => void; showLabel?: boolean }): JSX.Element {
    return (
        <LemonButton
            size="xsmall"
            type="primary"
            icon={<IconPulse />}
            onClick={onClick}
            tooltip={!showLabel ? 'Create anomaly alert' : undefined}
            data-attr="create-anomaly-alert-button"
        >
            {showLabel && 'Create anomaly alert'}
        </LemonButton>
    )
}

function InsightMetaExtraControls({
    showLabel,
    surveyOpportunityInsight,
    onCreateAnomalyAlert,
    feedbackButtons,
}: InsightMetaExtraControlsProps): JSX.Element {
    return (
        <div className="flex items-center gap-1">
            {surveyOpportunityInsight ? (
                <SurveyOpportunityButton
                    insight={surveyOpportunityInsight}
                    disableAutoPromptSubmit={true}
                    source={SURVEY_CREATED_SOURCE.INSIGHT_CROSS_SELL}
                    fromProduct={ProductKey.PRODUCT_ANALYTICS}
                    showLabel={showLabel}
                    tooltip="Create a survey to understand why users are dropping off"
                />
            ) : null}
            {onCreateAnomalyAlert ? (
                <CreateAnomalyAlertButton onClick={onCreateAnomalyAlert} showLabel={showLabel} />
            ) : null}
            {feedbackButtons}
        </div>
    )
}

export interface InsightMetaContentProps {
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
    dataRetentionWarning?: string | null
    queryScanTooltip?: JSX.Element | null
    /** Whether the person can act on a finding. Without one the tile only notes that the query is slow. */
    queryScanActionable?: boolean
    warehouseSyncTooltip?: JSX.Element | null
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
    dataRetentionWarning,
    queryScanTooltip,
    queryScanActionable,
    warehouseSyncTooltip,
}: InsightMetaContentProps): JSX.Element {
    const dataRetentionIndicator = dataRetentionWarning ? (
        <Tooltip title={dataRetentionWarning}>
            <IconWarning className="ml-1.5 text-base shrink-0 text-warning" />
        </Tooltip>
    ) : null
    const queryScanIndicator = queryScanTooltip ? (
        <Tooltip title={queryScanTooltip}>
            {queryScanActionable ? (
                <LemonTag type="warning" size="small" className="ml-1.5 shrink-0" data-attr="insight-card-query-scan">
                    Slow query
                </LemonTag>
            ) : (
                <IconClock
                    className="ml-1.5 text-base shrink-0 text-secondary"
                    data-attr="insight-card-query-scan-note"
                />
            )}
        </Tooltip>
    ) : null
    const warehouseSyncIndicator = warehouseSyncTooltip ? (
        <Tooltip title={warehouseSyncTooltip} interactive>
            <LemonTag type="warning" size="small" className="ml-1.5 shrink-0" data-attr="insight-card-warehouse-sync">
                Out of date
            </LemonTag>
        </Tooltip>
    ) : null
    const hasTitleIndicator = !!(infoPopover || dataRetentionIndicator || queryScanIndicator || warehouseSyncIndicator)
    const titleContent = (
        <>
            <span className={clsx('text-primary', hasTitleIndicator && 'truncate')}>
                {title || <i>{fallbackTitle || 'Untitled'}</i>}
            </span>
            {(loading || loadingQueued) && (
                <span className={clsx('text-sm font-medium ml-1.5', loading ? 'text-accent' : 'text-muted')}>
                    <Spinner className="mr-1.5 text-base" textColored />
                    {loading ? 'Loading' : 'Waiting to load'}
                </span>
            )}
        </>
    )

    const titleEl = (
        <h4
            title={!compact ? title : undefined}
            data-attr="insight-card-title"
            className={clsx(hasTitleIndicator && 'inline-flex items-center overflow-visible')}
        >
            {link ? (
                <Link to={link} className="max-w-full truncate">
                    {titleContent}
                </Link>
            ) : (
                titleContent
            )}
            {dataRetentionIndicator}
            {queryScanIndicator}
            {warehouseSyncIndicator}
            {infoPopover}
        </h4>
    )

    return (
        <>
            {titleEl}
            {showDescription !== false && !!description && (
                <LemonMarkdown className="CardMeta__description" lowKeyHeadings>
                    {description}
                </LemonMarkdown>
            )}
            {!compact && tags && tags.length > 0 && <ObjectTags tags={tags} staticOnly />}
            <LemonTableLoader loading={loading} />
        </>
    )
}
