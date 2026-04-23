import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { smoothingOptions } from 'lib/components/SmoothingFilter/smoothings'
import { FEATURE_FLAGS, NON_BREAKDOWN_DISPLAY_TYPES } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { axisLabel } from 'scenes/insights/aggregationAxisFormat'
import { Attribution } from 'scenes/insights/EditorFilters/AttributionFilter'
import { BoxPlotOutliersFilter } from 'scenes/insights/EditorFilters/BoxPlotOutliersFilter'
import { CompareEditorFilter } from 'scenes/insights/EditorFilters/CompareEditorFilter'
import { ConfidenceIntervalsEditorFilter } from 'scenes/insights/EditorFilters/ConfidenceIntervalsEditorFilter'
import { DecimalPlacesEditorFilter } from 'scenes/insights/EditorFilters/DecimalPlacesEditorFilter'
import { FunnelsAdvanced } from 'scenes/insights/EditorFilters/FunnelsAdvanced'
import { FunnelsQuerySteps } from 'scenes/insights/EditorFilters/FunnelsQuerySteps'
import { FunnelStepConfiguration } from 'scenes/insights/EditorFilters/FunnelStepConfiguration'
import { GoalLines } from 'scenes/insights/EditorFilters/GoalLines'
import { HideWeekendsFilter } from 'scenes/insights/EditorFilters/HideWeekendsFilter'
import { LifecycleStackingFilter } from 'scenes/insights/EditorFilters/LifecycleStackingFilter'
import { MovingAverageEditorFilter } from 'scenes/insights/EditorFilters/MovingAverageEditorFilter'
import { PathsAdvanced } from 'scenes/insights/EditorFilters/PathsAdvanced'
import { PathsEventsTypes } from 'scenes/insights/EditorFilters/PathsEventTypes'
import { PathsExclusions } from 'scenes/insights/EditorFilters/PathsExclusions'
import { PathsHogQL } from 'scenes/insights/EditorFilters/PathsHogQL'
import { PathsTargetEnd, PathsTargetStart } from 'scenes/insights/EditorFilters/PathsTarget'
import { PathsWildcardGroups } from 'scenes/insights/EditorFilters/PathsWildcardGroups'
import { PercentStackViewFilter } from 'scenes/insights/EditorFilters/PercentStackViewFilter'
import { PoeFilter } from 'scenes/insights/EditorFilters/PoeFilter'
import { ResultCustomizationByPicker } from 'scenes/insights/EditorFilters/ResultCustomizationByPicker'
import { RetentionCondition } from 'scenes/insights/EditorFilters/RetentionCondition'
import { RetentionDashboardEditorFilter } from 'scenes/insights/EditorFilters/RetentionDashboardEditorFilter'
import { RetentionOptions } from 'scenes/insights/EditorFilters/RetentionOptions'
import { SamplingDeprecationNotice } from 'scenes/insights/EditorFilters/SamplingDeprecationNotice'
import { ScalePicker } from 'scenes/insights/EditorFilters/ScalePicker'
import { ShowAlertAnomalyPointsFilter } from 'scenes/insights/EditorFilters/ShowAlertAnomalyPointsFilter'
import { ShowAlertThresholdLinesFilter } from 'scenes/insights/EditorFilters/ShowAlertThresholdLinesFilter'
import { ShowLegendFilter } from 'scenes/insights/EditorFilters/ShowLegendFilter'
import { ShowMultipleYAxesFilter } from 'scenes/insights/EditorFilters/ShowMultipleYAxesFilter'
import { ShowPieTotalFilter } from 'scenes/insights/EditorFilters/ShowPieTotalFilter'
import { ShowTrendLinesFilter } from 'scenes/insights/EditorFilters/ShowTrendLinesFilter'
import { SmoothingEditorFilter } from 'scenes/insights/EditorFilters/SmoothingEditorFilter'
import { UnitPickerEditorFilter } from 'scenes/insights/EditorFilters/UnitPickerEditorFilter'
import { ValueOnSeriesFilter } from 'scenes/insights/EditorFilters/ValueOnSeriesFilter'
import { WebAnalyticsEditorFilters } from 'scenes/insights/EditorFilters/WebAnalyticsEditorFilters'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { FunnelVizType } from 'scenes/insights/views/Funnels/FunnelVizType'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { userLogic } from 'scenes/userLogic'

import { StickinessCriteria } from '~/queries/nodes/InsightViz/StickinessCriteria'
import { FunnelsQuery, InsightQueryNode, WebOverviewQuery, WebStatsTableQuery } from '~/queries/schema/schema-general'
import { hasBreakdownFilter, isWebAnalyticsInsightQuery } from '~/queries/utils'
import {
    AvailableFeature,
    ChartDisplayType,
    EditorFilterProps,
    FunnelVizType as FunnelVizTypeEnum,
    InsightEditorFilterGroup,
    PathType,
} from '~/types'

import { Breakdown } from './Breakdown'
import { CumulativeStickinessFilter } from './CumulativeStickinessFilter'
import { EditorFilterGroup } from './EditorFilterGroup'
import { EditorFiltersShell } from './EditorFiltersShell'
import { getBreakdownSummary, getFiltersSummary, getSeriesSummary, visibleFilters } from './editorFilterUtils'
import { GlobalAndOrFilters } from './GlobalAndOrFilters'
import { LifecycleToggles } from './LifecycleToggles'
import { TrendsSeries } from './TrendsSeries'

export interface EditorFiltersProps {
    query: InsightQueryNode
    showing: boolean
    embedded: boolean
}

export function EditorFilters({ query, showing, embedded }: EditorFiltersProps): JSX.Element | null {
    const { hasAvailableFeature } = useValues(userLogic)

    const { insightProps } = useValues(insightLogic)
    const {
        isTrends,
        isFunnels,
        isRetention,
        isPaths,
        isLifecycle,
        isStickiness,
        isTrendsLike,
        display,
        pathsFilter,
        querySource,
        series,
        breakdownFilter,
        properties,
        isNonTimeSeriesDisplay,
        supportsValueOnSeries,
        supportsPercentStackView,
        hasLegend,
        supportsResultCustomizationBy,
        showPercentStackView,
        interval,
    } = useValues(insightVizDataLogic(insightProps))

    const { isStepsFunnel, isTrendsFunnel } = useValues(funnelDataLogic(insightProps))
    const { mightContainFractionalNumbers } = useValues(trendsDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)

    if (!querySource) {
        return null
    }

    // Web Analytics insights use their custom filter UI
    if (isWebAnalyticsInsightQuery(query)) {
        return (
            <WebAnalyticsEditorFilters
                query={query as WebOverviewQuery | WebStatsTableQuery}
                showing={showing}
                embedded={embedded}
            />
        )
    }

    const hideWeekendsEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_HIDE_WEEKENDS]

    const hasBreakdown =
        (isTrends && !NON_BREAKDOWN_DISPLAY_TYPES.includes(display || ChartDisplayType.ActionsLineGraph)) ||
        isStepsFunnel ||
        isTrendsFunnel ||
        isRetention
    const hasPathsAdvanced = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)
    const hasAttribution = isStepsFunnel || isTrendsFunnel
    const hasPathsHogQL = isPaths && pathsFilter?.includeEventTypes?.includes(PathType.HogQL)
    const displayGoalLines =
        (isTrends &&
            [
                ChartDisplayType.ActionsLineGraph,
                ChartDisplayType.ActionsLineGraphCumulative,
                ChartDisplayType.ActionsAreaGraph,
                ChartDisplayType.ActionsBar,
                ChartDisplayType.ActionsUnstackedBar,
            ].includes(display || ChartDisplayType.ActionsLineGraph)) ||
        (isFunnels && isTrendsFunnel) ||
        (isRetention &&
            [ChartDisplayType.ActionsLineGraph, ChartDisplayType.ActionsBar].includes(
                display || ChartDisplayType.ActionsLineGraph
            ))

    const showCompare =
        (isTrends &&
            display !== ChartDisplayType.ActionsAreaGraph &&
            display !== ChartDisplayType.CalendarHeatmap &&
            display !== ChartDisplayType.BoxPlot) ||
        isStickiness ||
        isWebAnalyticsInsightQuery(querySource)

    const showSmoothing =
        isTrends &&
        !hasBreakdownFilter(breakdownFilter) &&
        (!display || display === ChartDisplayType.ActionsLineGraph || display === ChartDisplayType.ActionsAreaGraph) &&
        (smoothingOptions[interval ?? 'day']?.length ?? 0) > 0

    const isNonTimeSeries = isNonTimeSeriesDisplay
    const showYAxisOptions = isTrends && display !== ChartDisplayType.CalendarHeatmap && !isNonTimeSeries
    const showStatisticalAnalysis = showYAxisOptions && display !== ChartDisplayType.BoxPlot
    const showDecimalPlaces = mightContainFractionalNumbers && isTrends && display !== ChartDisplayType.CalendarHeatmap
    const isBoxPlot = display === ChartDisplayType.BoxPlot

    const seriesSummary = getSeriesSummary(series)
    const filtersSummary = getFiltersSummary(properties)
    const breakdownSummary = getBreakdownSummary(breakdownFilter)
    const exclusionCount = isPaths ? (pathsFilter?.excludeEvents?.length ?? 0) : 0
    const exclusionsSummary = exclusionCount > 0 ? pluralize(exclusionCount, 'exclusion') : null

    const leftEditorFilterGroups: InsightEditorFilterGroup[] = [
        {
            title: 'Retention condition',
            defaultExpanded: true,
            show: isRetention,
            editorFilters: [{ key: 'retention-condition', component: RetentionCondition }],
        },
        {
            title: 'Calculation options',
            defaultExpanded: false,
            show: isRetention,
            editorFilters: [{ key: 'retention-options', component: RetentionOptions }],
        },
        {
            title: isFunnels ? 'Steps' : 'General',
            show: !isRetention,
            defaultExpanded: true,
            headerExtra:
                isFunnels && (querySource as FunnelsQuery)?.funnelsFilter?.funnelVizType !== FunnelVizTypeEnum.Flow ? (
                    <Tooltip docLink="https://posthog.com/docs/product-analytics/funnels#graph-type">
                        <FunnelVizType insightProps={insightProps} />
                    </Tooltip>
                ) : null,
            editorFilters: visibleFilters([
                { key: 'query-steps', component: FunnelsQuerySteps, show: isFunnels },
                { key: 'event-types', label: 'Event Types', component: PathsEventsTypes, show: isPaths },
                {
                    key: 'hogql',
                    label: 'SQL Expression',
                    component: PathsHogQL,
                    show: isPaths && !!hasPathsHogQL,
                },
                {
                    key: 'wildcard-groups',
                    label: 'Wildcard Groups',
                    showOptional: true,
                    component: PathsWildcardGroups,
                    show: isPaths && hasPathsAdvanced,
                    tooltip: (
                        <>
                            Use wildcard matching to group events by unique values in path item names. Use an asterisk
                            (*) in place of unique values. For example, instead of /merchant/1234/payment, replace the
                            unique value with an asterisk /merchant/*/payment.{' '}
                            <b>Use a comma to separate multiple wildcards.</b>
                        </>
                    ),
                },
                { key: 'start-target', label: 'Starts at', component: PathsTargetStart, show: isPaths },
                {
                    key: 'ends-target',
                    label: 'Ends at',
                    component: PathsTargetEnd,
                    show: isPaths && hasPathsAdvanced,
                },
            ]),
        },
        {
            title: 'Series',
            defaultExpanded: true,
            collapsedSummary: seriesSummary,
            editorFilters: visibleFilters([
                {
                    key: 'series',
                    component: TrendsSeries,
                    show: isTrendsLike,
                },
            ]),
        },
        {
            title: isFunnels ? 'Funnel settings' : isPaths ? 'Path settings' : 'Advanced options',
            defaultExpanded: false,
            editorFilters: visibleFilters([
                { key: 'paths-advanced', component: PathsAdvanced, show: isPaths },
                {
                    key: 'funnel-step-configuration',
                    component: FunnelStepConfiguration,
                    show: isFunnels,
                },
                { key: 'funnels-advanced', component: FunnelsAdvanced, show: isFunnels },
            ]),
        },
    ]

    const rightEditorFilterGroups: InsightEditorFilterGroup[] = [
        {
            title: 'Filters',
            defaultExpanded: false,
            collapsedSummary: filtersSummary,
            editorFilters: visibleFilters([
                {
                    key: 'toggles',
                    label: 'Lifecycle Toggles',
                    component: LifecycleToggles as (props: EditorFilterProps) => JSX.Element | null,
                    show: isLifecycle,
                },
                {
                    key: 'stickinessCriteria',
                    label: () => (
                        <div className="flex">
                            <span>Stickiness Criteria</span>
                            <Tooltip
                                closeDelayMs={200}
                                title={
                                    <div className="deprecated-space-y-2">
                                        <div>
                                            The stickiness criteria defines how many times a user must perform an event
                                            inside of a given interval in order to be considered "sticky."
                                        </div>
                                    </div>
                                }
                            >
                                <IconInfo className="text-xl text-secondary shrink-0 ml-1" />
                            </Tooltip>
                        </div>
                    ),
                    component: StickinessCriteria as (props: EditorFilterProps) => JSX.Element | null,
                    show: isStickiness,
                },
                {
                    key: 'cumulativeStickiness',
                    label: () => (
                        <div className="flex">
                            <span>Compute as</span>
                            <Tooltip
                                closeDelayMs={200}
                                title={
                                    <div className="deprecated-space-y-2">
                                        <div>
                                            Choose how to compute stickiness values. Non-cumulative shows exact numbers
                                            for each day count, while cumulative shows users active for at least that
                                            many days.
                                        </div>
                                    </div>
                                }
                            >
                                <IconInfo className="text-xl text-secondary shrink-0 ml-1" />
                            </Tooltip>
                        </div>
                    ),
                    component: CumulativeStickinessFilter as (props: EditorFilterProps) => JSX.Element | null,
                    show: isStickiness,
                },
                {
                    key: 'properties',
                    label: undefined,
                    component: GlobalAndOrFilters as (props: EditorFilterProps) => JSX.Element | null,
                },
            ]),
        },
        {
            title: 'Breakdown',
            defaultExpanded: false,
            collapsedSummary: breakdownSummary,
            editorFilters: visibleFilters([
                { key: 'breakdown', component: Breakdown, show: hasBreakdown },
                {
                    key: 'attribution',
                    label: () => (
                        <div className="flex">
                            <span>Breakdown attribution</span>
                            <Tooltip
                                closeDelayMs={200}
                                interactive
                                title={
                                    <div className="deprecated-space-y-2">
                                        <div>
                                            When breaking down funnels, it's possible that the same properties don't
                                            exist on every event. For example, if you want to break down by browser on a
                                            funnel that contains both frontend and backend events.
                                        </div>
                                        <div>
                                            In this case, you can choose from which step the properties should be
                                            selected from by modifying the attribution type. There are four modes to
                                            choose from:
                                        </div>
                                        <ul className="list-disc pl-4">
                                            <li>
                                                First touchpoint: the first property value seen in any of the steps is
                                                chosen.
                                            </li>
                                            <li>
                                                Last touchpoint: the last property value seen from all steps is chosen.
                                            </li>
                                            <li>
                                                All steps: the property value must be seen in all steps to be considered
                                                in the funnel.
                                            </li>
                                            <li>
                                                Specific step: only the property value seen at the selected step is
                                                chosen.
                                            </li>
                                        </ul>
                                        <div>
                                            Read more in the{' '}
                                            <Link to="https://posthog.com/docs/product-analytics/funnels#attribution-types">
                                                documentation.
                                            </Link>
                                        </div>
                                    </div>
                                }
                            >
                                <IconInfo className="text-xl text-secondary shrink-0 ml-1" />
                            </Tooltip>
                        </div>
                    ),
                    component: Attribution,
                    show: hasAttribution,
                },
            ]),
        },
        {
            title: 'Exclusions',
            defaultExpanded: false,
            collapsedSummary: exclusionsSummary,
            editorFilters: visibleFilters([
                {
                    key: 'paths-exclusions',
                    label: 'Exclusions',
                    tooltip: (
                        <>Exclude events from Paths visualisation. You can use wildcard groups in exclusions as well.</>
                    ),
                    component: PathsExclusions,
                    show: isPaths,
                },
            ]),
        },
        {
            title: 'Compare',
            defaultExpanded: false,
            show: showCompare,
            editorFilters: [{ key: 'compare', component: CompareEditorFilter }],
        },
        {
            title: 'Visualization',
            defaultExpanded: false,
            show:
                (isTrends && display !== ChartDisplayType.CalendarHeatmap) ||
                isRetention ||
                isTrendsFunnel ||
                isStickiness ||
                isLifecycle,
            editorFilters: visibleFilters([
                { key: 'lifecycle-stacking', component: LifecycleStackingFilter, show: isLifecycle },
                { key: 'value-on-series', component: ValueOnSeriesFilter, show: !!supportsValueOnSeries },
                { key: 'percent-stack-view', component: PercentStackViewFilter, show: !!supportsPercentStackView },
                { key: 'show-legend', component: ShowLegendFilter, show: !!hasLegend },
                { key: 'pie-total', component: ShowPieTotalFilter, show: display === ChartDisplayType.ActionsPie },
                {
                    key: 'alert-threshold-lines',
                    component: ShowAlertThresholdLinesFilter,
                    show: isTrends && !isNonTimeSeriesDisplay,
                },
                {
                    key: 'alert-anomaly-points',
                    component: ShowAlertAnomalyPointsFilter,
                    show: isTrends && !isNonTimeSeriesDisplay,
                },
                {
                    key: 'multiple-y-axes',
                    component: ShowMultipleYAxesFilter,
                    show: (isTrends || isStickiness) && !isNonTimeSeriesDisplay,
                },
                {
                    key: 'trend-lines',
                    component: ShowTrendLinesFilter,
                    show: (isTrends || isRetention || isTrendsFunnel) && !isNonTimeSeriesDisplay,
                },
                {
                    key: 'hide-weekends',
                    component: HideWeekendsFilter,
                    show: isTrends && !isNonTimeSeriesDisplay && hideWeekendsEnabled,
                },
                { key: 'box-plot-outliers', component: BoxPlotOutliersFilter, show: isBoxPlot },
                {
                    key: 'result-customization-by',
                    component: ResultCustomizationByPicker,
                    show: !!supportsResultCustomizationBy,
                },
            ]),
        },
        // Hide advanced options for calendar heatmap
        {
            title: 'Advanced options',
            defaultExpanded: false,
            show: display !== ChartDisplayType.CalendarHeatmap,
            editorFilters: visibleFilters([
                { key: 'smoothing', label: 'Smoothing', component: SmoothingEditorFilter, show: showSmoothing },
                {
                    key: 'y-axis-unit',
                    label: axisLabel(display || ChartDisplayType.ActionsLineGraph),
                    component: UnitPickerEditorFilter,
                    show: !showPercentStackView && isTrends && display !== ChartDisplayType.CalendarHeatmap,
                },
                { key: 'y-axis-scale', label: 'Y-axis scale', component: ScalePicker, show: showYAxisOptions },
                {
                    key: 'confidence-intervals',
                    label: 'Confidence intervals',
                    component: ConfidenceIntervalsEditorFilter,
                    show: showStatisticalAnalysis,
                },
                {
                    key: 'moving-average',
                    label: 'Moving average',
                    component: MovingAverageEditorFilter,
                    show: showStatisticalAnalysis,
                },
                {
                    key: 'decimal-places',
                    label: 'Decimal places',
                    component: DecimalPlacesEditorFilter,
                    show: showDecimalPlaces,
                },
                {
                    key: 'retention-dashboard',
                    label: 'On dashboards',
                    component: RetentionDashboardEditorFilter,
                    show: isRetention,
                },
                { key: 'poe', component: PoeFilter },
                {
                    key: 'goal-lines',
                    label: 'Goal lines',
                    tooltip: (
                        <>
                            Goal lines can be used to highlight specific goals (Revenue, Signups, etc.) or limits (Web
                            Vitals, etc.)
                        </>
                    ),
                    component: GoalLines,
                    show: displayGoalLines,
                },
                { key: 'sampling-deprecation', component: SamplingDeprecationNotice },
            ]),
        },
    ]

    const visibleGroups = (groups: InsightEditorFilterGroup[]): InsightEditorFilterGroup[] =>
        groups.filter((g) => g.show !== false && g.editorFilters.length > 0)

    const allFilterGroups = [...visibleGroups(leftEditorFilterGroups), ...visibleGroups(rightEditorFilterGroups)]

    return (
        <EditorFiltersShell query={query} showing={showing} embedded={embedded}>
            <div className="flex flex-col gap-3">
                {allFilterGroups.map((editorFilterGroup) => (
                    <EditorFilterGroup
                        key={editorFilterGroup.title}
                        editorFilterGroup={editorFilterGroup}
                        insightProps={insightProps}
                        queryKind={querySource?.kind}
                    />
                ))}
            </div>
        </EditorFiltersShell>
    )
}
