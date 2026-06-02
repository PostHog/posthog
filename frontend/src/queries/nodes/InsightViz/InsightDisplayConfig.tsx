import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { ReactNode } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconEllipsis, IconInfo } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { ChartFilter } from 'lib/components/ChartFilter'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { smoothingOptions } from 'lib/components/SmoothingFilter/smoothings'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { FEATURE_FLAGS, NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { normalizeAxisLabel } from 'lib/hog-charts/utils/axis-labels'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DEFAULT_DECIMAL_PLACES } from 'lib/utils'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { axisLabel } from 'scenes/insights/aggregationAxisFormat'
import { AxisLabelsFilter } from 'scenes/insights/EditorFilters/AxisLabelsFilter'
import { HideWeekendsFilter } from 'scenes/insights/EditorFilters/HideWeekendsFilter'
import { LifecycleStackingFilter } from 'scenes/insights/EditorFilters/LifecycleStackingFilter'
import { PercentStackViewFilter } from 'scenes/insights/EditorFilters/PercentStackViewFilter'
import { ResultCustomizationByPicker } from 'scenes/insights/EditorFilters/ResultCustomizationByPicker'
import { ScalePicker } from 'scenes/insights/EditorFilters/ScalePicker'
import { ShowAlertAnomalyPointsFilter } from 'scenes/insights/EditorFilters/ShowAlertAnomalyPointsFilter'
import { ShowAlertThresholdLinesFilter } from 'scenes/insights/EditorFilters/ShowAlertThresholdLinesFilter'
import { ShowLegendFilter } from 'scenes/insights/EditorFilters/ShowLegendFilter'
import { ShowMultipleYAxesFilter } from 'scenes/insights/EditorFilters/ShowMultipleYAxesFilter'
import { ShowPieTotalFilter } from 'scenes/insights/EditorFilters/ShowPieTotalFilter'
import { ShowTrendLinesFilter } from 'scenes/insights/EditorFilters/ShowTrendLinesFilter'
import { ValueOnSeriesFilter } from 'scenes/insights/EditorFilters/ValueOnSeriesFilter'
import { InsightDateFilter } from 'scenes/insights/filters/InsightDateFilter'
import { RetentionChartPicker } from 'scenes/insights/filters/RetentionChartPicker'
import { RetentionCohortLabelStartIndexPicker } from 'scenes/insights/filters/RetentionCohortLabelStartIndexPicker'
import { RetentionDashboardDisplayPicker } from 'scenes/insights/filters/RetentionDashboardDisplayPicker'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { RetentionDatePicker } from 'scenes/insights/RetentionDatePicker'
import { FunnelBinsPicker } from 'scenes/insights/views/Funnels/FunnelBinsPicker'
import { FunnelDisplayLayoutPicker } from 'scenes/insights/views/Funnels/FunnelDisplayLayoutPicker'
import { ConfidenceLevelInput } from 'scenes/insights/views/LineGraph/ConfidenceLevelInput'
import { MovingAverageIntervalsInput } from 'scenes/insights/views/LineGraph/MovingAverageIntervalsInput'
import { PathStepPicker } from 'scenes/insights/views/Paths/PathStepPicker'
import { RetentionBreakdownFilter } from 'scenes/retention/RetentionBreakdownFilter'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { hasBreakdownFilter, isWebAnalyticsInsightQuery } from '~/queries/utils'
import { isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

const LINE_DISPLAYS = [
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsLineGraphCumulative,
    ChartDisplayType.ActionsAreaGraph,
] as const
const BAR_DISPLAYS = [
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsUnstackedBar,
    ChartDisplayType.ActionsBarValue,
] as const

function displayMatches(display: ChartDisplayType | null | undefined, displays: readonly ChartDisplayType[]): boolean {
    return !!display && displays.includes(display)
}

function isDefaultTrendsLineDisplay(
    display: ChartDisplayType | null | undefined,
    querySource: Parameters<typeof isTrendsQuery>[0]
): boolean {
    return !display && isTrendsQuery(querySource)
}

export function InsightDisplayConfig(): JSX.Element {
    const { insightProps, canEditInsight, editingDisabledReason } = useValues(insightLogic)

    const {
        querySource,
        isTrends,
        isFunnels,
        isRetention,
        isPaths,
        isStickiness,
        isLifecycle,
        supportsDisplay,
        display,
        breakdownFilter,
        trendsFilter,
        hasLegend,
        showLegend,
        supportsValueOnSeries,
        showPercentStackView,
        supportsPercentStackView,
        supportsResultCustomizationBy,
        yAxisScaleType,
        showMultipleYAxes,
        isNonTimeSeriesDisplay,
        compareFilter,
        supportsCompare,
        interval,
    } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource, updateCompareFilter } = useActions(insightVizDataLogic(insightProps))
    const { isTrendsFunnel, isStepsFunnel, isTimeToConvertFunnel, isEmptyFunnel } = useValues(
        funnelDataLogic(insightProps)
    )
    const { featureFlags } = useValues(featureFlagLogic)
    const hideWeekendsEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_HIDE_WEEKENDS]

    const showCompare =
        (isTrends &&
            display !== ChartDisplayType.ActionsAreaGraph &&
            display !== ChartDisplayType.CalendarHeatmap &&
            display !== ChartDisplayType.BoxPlot) ||
        isStickiness ||
        isWebAnalyticsInsightQuery(querySource)
    const showInterval =
        isTrendsFunnel ||
        isLifecycle ||
        ((isTrends || isStickiness) && !(display && NON_TIME_SERIES_DISPLAY_TYPES.includes(display)))
    const showSmoothing =
        isTrends &&
        !hasBreakdownFilter(breakdownFilter) &&
        (!display || display === ChartDisplayType.ActionsLineGraph || display === ChartDisplayType.ActionsAreaGraph) &&
        !!interval &&
        (smoothingOptions[interval]?.length ?? 0) > 0
    const showMultipleYAxesConfig = (isTrends || isStickiness) && !isNonTimeSeriesDisplay
    const showAlertThresholdLinesConfig = isTrends && !isNonTimeSeriesDisplay
    const isLineDisplay = isDefaultTrendsLineDisplay(display, querySource) || displayMatches(display, LINE_DISPLAYS)
    const isBarDisplay = displayMatches(display, BAR_DISPLAYS)
    const isCumulativeLineDisplay = display === ChartDisplayType.ActionsLineGraphCumulative
    const showAxisLabelsConfig =
        isTrends && (isLineDisplay || isBarDisplay) && featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_HOG_CHARTS_TRENDS]
    const isLineGraph = isLineDisplay && !isCumulativeLineDisplay
    const isLinearScale = !yAxisScaleType || yAxisScaleType === 'linear'

    const { showValuesOnSeries, mightContainFractionalNumbers, showConfidenceIntervals, showMovingAverage } = useValues(
        trendsDataLogic(insightProps)
    )

    const isBoxPlot = display === ChartDisplayType.BoxPlot
    const advancedOptions: LemonMenuItems = [
        ...(showSmoothing
            ? [
                  {
                      title: 'Smoothing',
                      items: [
                          {
                              label: () => (
                                  <div className="px-2 pb-1.5 w-full">
                                      <SmoothingFilter />
                                  </div>
                              ),
                          },
                      ],
                  },
              ]
            : []),
        ...((isTrends && display !== ChartDisplayType.CalendarHeatmap) ||
        isRetention ||
        isTrendsFunnel ||
        isStickiness ||
        isLifecycle
            ? [
                  {
                      title: (
                          <h5 className="mx-2 my-1" data-attr="options-display-section">
                              Display
                          </h5>
                      ),
                      items: isBoxPlot
                          ? [
                                ...(hasLegend ? [{ label: () => <ShowLegendFilter /> }] : []),
                                {
                                    label: () => (
                                        <LemonCheckbox
                                            label={
                                                <span className="font-normal">
                                                    Exclude outliers{' '}
                                                    <Tooltip title="When enabled, whiskers are clipped to 1.5x the interquartile range, making it easier to see differences between the quartiles. When disabled, the y-axis extends to show the full range including extreme values.">
                                                        <IconInfo className="relative top-0.5 text-lg text-secondary" />
                                                    </Tooltip>
                                                </span>
                                            }
                                            className="p-1 px-2"
                                            size="small"
                                            checked={trendsFilter?.excludeBoxPlotOutliers !== false}
                                            onChange={(checked) => {
                                                if (isTrendsQuery(querySource)) {
                                                    const newQuery = { ...querySource }
                                                    newQuery.trendsFilter = {
                                                        ...trendsFilter,
                                                        excludeBoxPlotOutliers: checked,
                                                    }
                                                    updateQuerySource(newQuery)
                                                }
                                            }}
                                        />
                                    ),
                                },
                            ]
                          : [
                                ...(isLifecycle ? [{ label: () => <LifecycleStackingFilter /> }] : []),
                                ...(supportsValueOnSeries ? [{ label: () => <ValueOnSeriesFilter /> }] : []),
                                ...(supportsPercentStackView ? [{ label: () => <PercentStackViewFilter /> }] : []),
                                ...(hasLegend ? [{ label: () => <ShowLegendFilter /> }] : []),
                                ...(display === ChartDisplayType.ActionsPie
                                    ? [{ label: () => <ShowPieTotalFilter /> }]
                                    : []),
                                ...(showAlertThresholdLinesConfig
                                    ? [
                                          { label: () => <ShowAlertThresholdLinesFilter /> },
                                          { label: () => <ShowAlertAnomalyPointsFilter /> },
                                      ]
                                    : []),
                                ...(showMultipleYAxesConfig ? [{ label: () => <ShowMultipleYAxesFilter /> }] : []),
                                ...((isTrends || isRetention || isTrendsFunnel) && !isNonTimeSeriesDisplay
                                    ? [{ label: () => <ShowTrendLinesFilter /> }]
                                    : []),
                                ...(isTrends && !isNonTimeSeriesDisplay && hideWeekendsEnabled
                                    ? [{ label: () => <HideWeekendsFilter /> }]
                                    : []),
                            ],
                  },
              ]
            : []),
        ...(supportsResultCustomizationBy
            ? [
                  {
                      title: (
                          <>
                              <h5 className="mx-2 my-1">
                                  Color customization by{' '}
                                  <Tooltip title="You can customize the appearance of individual results in your insights. This can be done based on the result's name (e.g., customize the breakdown value 'pizza' for the first series) or based on the result's rank (e.g., customize the first dataset in the results).">
                                      <IconInfo className="relative top-0.5 text-lg text-secondary" />
                                  </Tooltip>
                              </h5>
                          </>
                      ),
                      items: [{ label: () => <ResultCustomizationByPicker /> }],
                  },
              ]
            : []),
        ...(!showPercentStackView && isTrends && display !== ChartDisplayType.CalendarHeatmap
            ? [
                  {
                      title: axisLabel(display || ChartDisplayType.ActionsLineGraph),
                      items: [{ label: () => <UnitPicker /> }],
                  },
              ]
            : []),
        ...(!isNonTimeSeriesDisplay && isTrends && display !== ChartDisplayType.CalendarHeatmap
            ? [
                  {
                      title: 'Y-axis scale',
                      items: [{ label: () => <ScalePicker /> }],
                  },
                  ...(display === ChartDisplayType.BoxPlot
                      ? []
                      : [
                            {
                                title: 'Statistical analysis',
                                items: [
                                    {
                                        label: () => (
                                            <LemonSwitch
                                                label="Show confidence intervals"
                                                className="pb-2"
                                                fullWidth
                                                checked={showConfidenceIntervals}
                                                disabledReason={
                                                    !isLineGraph
                                                        ? 'Confidence intervals are only available for line graphs'
                                                        : !isLinearScale
                                                          ? 'Confidence intervals are only supported for linear scale.'
                                                          : undefined
                                                }
                                                onChange={(checked) => {
                                                    if (isTrendsQuery(querySource)) {
                                                        const newQuery = { ...querySource }
                                                        newQuery.trendsFilter = {
                                                            ...trendsFilter,
                                                            showConfidenceIntervals: checked,
                                                        }
                                                        updateQuerySource(newQuery)
                                                    }
                                                }}
                                            />
                                        ),
                                    },
                                    ...(showConfidenceIntervals
                                        ? [
                                              {
                                                  label: () => <ConfidenceLevelInput />,
                                              },
                                          ]
                                        : []),
                                    {
                                        label: () => (
                                            <LemonSwitch
                                                label="Show moving average"
                                                className="pb-2"
                                                fullWidth
                                                checked={showMovingAverage}
                                                disabledReason={
                                                    !isLineGraph
                                                        ? 'Moving average is only available for line and area graphs'
                                                        : !isLinearScale
                                                          ? 'Moving average is only supported for linear scale.'
                                                          : undefined
                                                }
                                                onChange={(checked) => {
                                                    if (isTrendsQuery(querySource)) {
                                                        const newQuery = { ...querySource }
                                                        newQuery.trendsFilter = {
                                                            ...trendsFilter,
                                                            showMovingAverage: checked,
                                                        }
                                                        updateQuerySource(newQuery)
                                                    }
                                                }}
                                            />
                                        ),
                                    },
                                    ...(showMovingAverage
                                        ? [
                                              {
                                                  label: () => <MovingAverageIntervalsInput />,
                                              },
                                          ]
                                        : []),
                                ],
                            },
                        ]),
              ]
            : []),
        ...(showAxisLabelsConfig
            ? [
                  {
                      title: 'Axis labels',
                      items: [{ label: () => <AxisLabelsFilter /> }],
                  },
              ]
            : []),
        ...(mightContainFractionalNumbers && isTrends && display !== ChartDisplayType.CalendarHeatmap
            ? [
                  {
                      title: 'Decimal places',
                      items: [{ label: () => <DecimalPrecisionInput /> }],
                  },
              ]
            : []),
        ...(isRetention
            ? [
                  {
                      title: 'On dashboards',
                      items: [{ label: () => <RetentionDashboardDisplayPicker /> }],
                  },
                  {
                      title: (
                          <h5 className="mx-2 my-1">
                              Cohort labels start at{' '}
                              <Tooltip title="Controls the starting index used to label cohort columns. Display only, does not affect the calculations.">
                                  <IconInfo className="relative top-0.5 text-lg text-secondary" />
                              </Tooltip>
                          </h5>
                      ),
                      items: [{ label: () => <RetentionCohortLabelStartIndexPicker /> }],
                  },
              ]
            : []),
    ]
    const advancedOptionsCount: number =
        (showSmoothing && (trendsFilter?.smoothingIntervals ?? 1) !== 1 ? 1 : 0) +
        (supportsValueOnSeries && showValuesOnSeries ? 1 : 0) +
        (showPercentStackView ? 1 : 0) +
        (!showPercentStackView &&
        isTrends &&
        trendsFilter?.aggregationAxisFormat &&
        trendsFilter.aggregationAxisFormat !== 'numeric'
            ? 1
            : 0) +
        (hasLegend && showLegend ? 1 : 0) +
        (!!yAxisScaleType && yAxisScaleType !== 'linear' ? 1 : 0) +
        (showAxisLabelsConfig && normalizeAxisLabel(trendsFilter?.xAxisLabel) ? 1 : 0) +
        (showAxisLabelsConfig && normalizeAxisLabel(trendsFilter?.yAxisLabel) ? 1 : 0) +
        (showMultipleYAxes ? 1 : 0) +
        (trendsFilter?.hideWeekends && hideWeekendsEnabled ? 1 : 0)

    return (
        <div
            className="InsightDisplayConfig @container flex justify-between items-center flex-wrap gap-2 [&_.LemonButton--small]:[--lemon-button-gap:0.25rem] [&_.LemonButton--small]:[--lemon-button-padding-horizontal:0.375rem]"
            data-attr="insight-filters"
        >
            <div className="flex items-center gap-x-2 flex-wrap gap-y-2">
                {!isRetention && (
                    <ConfigFilter>
                        <InsightDateFilter disabled={isFunnels && !!isEmptyFunnel} />
                    </ConfigFilter>
                )}

                {showInterval && (
                    <ConfigFilter>
                        <IntervalFilter />
                    </ConfigFilter>
                )}

                {!!isRetention && (
                    <ConfigFilter>
                        <RetentionDatePicker />
                        {hasBreakdownFilter(breakdownFilter) && <RetentionBreakdownFilter />}
                    </ConfigFilter>
                )}

                {!!isPaths && (
                    <ConfigFilter>
                        <PathStepPicker />
                    </ConfigFilter>
                )}

                {showCompare && (
                    <ConfigFilter>
                        <CompareFilter
                            compareFilter={compareFilter}
                            updateCompareFilter={updateCompareFilter}
                            disabled={!canEditInsight || !supportsCompare}
                            disableReason={editingDisabledReason}
                        />
                    </ConfigFilter>
                )}
            </div>
            <div className="flex items-center gap-x-2">
                {advancedOptions.length > 0 && (
                    <>
                        <LemonMenu items={advancedOptions} closeOnClickInside={false} placement="bottom-end">
                            <LemonButton
                                size="small"
                                disabledReason={editingDisabledReason}
                                aria-label="Options"
                                className="@max-[780px]:hidden"
                            >
                                <span className="font-medium whitespace-nowrap">
                                    Options
                                    {advancedOptionsCount ? (
                                        <span className="ml-0.5 text-secondary ligatures-none">
                                            ({advancedOptionsCount})
                                        </span>
                                    ) : null}
                                </span>
                            </LemonButton>
                        </LemonMenu>
                        <LemonMenu items={advancedOptions} closeOnClickInside={false} placement="bottom-end">
                            <LemonButton
                                size="small"
                                disabledReason={editingDisabledReason}
                                icon={<IconEllipsis />}
                                aria-label="Options"
                                className="hidden @max-[780px]:flex order-[999]"
                            />
                        </LemonMenu>
                    </>
                )}
                {supportsDisplay && (
                    <ConfigFilter>
                        <ChartFilter />
                    </ConfigFilter>
                )}
                {!!isRetention && (
                    <ConfigFilter>
                        <RetentionChartPicker />
                    </ConfigFilter>
                )}
                {!!isStepsFunnel && (
                    <ConfigFilter>
                        <FunnelDisplayLayoutPicker />
                    </ConfigFilter>
                )}
                {!!isTimeToConvertFunnel && (
                    <ConfigFilter>
                        <FunnelBinsPicker />
                    </ConfigFilter>
                )}
            </div>
        </div>
    )
}

function ConfigFilter({ children }: { children: ReactNode }): JSX.Element {
    return <span className="deprecated-space-x-2 flex items-center text-sm">{children}</span>
}

function DecimalPrecisionInput(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const reportChange = useDebouncedCallback(() => {
        posthog.capture('decimal places changed', {
            decimal_places: trendsFilter?.decimalPlaces,
        })
    }, 500)

    return (
        <LemonInput
            type="number"
            size="small"
            step={1}
            min={0}
            max={9}
            defaultValue={DEFAULT_DECIMAL_PLACES}
            value={trendsFilter?.decimalPlaces}
            onChange={(value) => {
                updateInsightFilter({
                    decimalPlaces: value,
                })
                reportChange()
            }}
            className="mx-2 mb-1.5"
        />
    )
}
