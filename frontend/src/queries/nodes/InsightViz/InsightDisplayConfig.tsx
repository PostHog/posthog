import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { ReactNode } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonInput, Tooltip } from '@posthog/lemon-ui'
import { LemonSwitch } from '@posthog/lemon-ui'

import { ChartFilter } from 'lib/components/ChartFilter'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { DEFAULT_DECIMAL_PLACES } from 'lib/utils'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { LifecycleStackingFilter } from 'scenes/insights/EditorFilters/LifecycleStackingFilter'
import { PercentStackViewFilter } from 'scenes/insights/EditorFilters/PercentStackViewFilter'
import { ResultCustomizationByPicker } from 'scenes/insights/EditorFilters/ResultCustomizationByPicker'
import { ScalePicker } from 'scenes/insights/EditorFilters/ScalePicker'
import { ShowAlertThresholdLinesFilter } from 'scenes/insights/EditorFilters/ShowAlertThresholdLinesFilter'
import { ShowLegendFilter } from 'scenes/insights/EditorFilters/ShowLegendFilter'
import { ShowMultipleYAxesFilter } from 'scenes/insights/EditorFilters/ShowMultipleYAxesFilter'
import { ShowTrendLinesFilter } from 'scenes/insights/EditorFilters/ShowTrendLinesFilter'
import { ValueOnSeriesFilter } from 'scenes/insights/EditorFilters/ValueOnSeriesFilter'
import { RetentionDatePicker } from 'scenes/insights/RetentionDatePicker'
import { axisLabel } from 'scenes/insights/aggregationAxisFormat'
import { InsightDateFilter } from 'scenes/insights/filters/InsightDateFilter'
import { RetentionChartPicker } from 'scenes/insights/filters/RetentionChartPicker'
import { RetentionDashboardDisplayPicker } from 'scenes/insights/filters/RetentionDashboardDisplayPicker'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { FunnelBinsPicker } from 'scenes/insights/views/Funnels/FunnelBinsPicker'
import { FunnelDisplayLayoutPicker } from 'scenes/insights/views/Funnels/FunnelDisplayLayoutPicker'
import { ConfidenceLevelInput } from 'scenes/insights/views/LineGraph/ConfidenceLevelInput'
import { MovingAverageIntervalsInput } from 'scenes/insights/views/LineGraph/MovingAverageIntervalsInput'
import { PathStepPicker } from 'scenes/insights/views/Paths/PathStepPicker'
import { RetentionBreakdownFilter } from 'scenes/retention/RetentionBreakdownFilter'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { isValidBreakdown } from '~/queries/utils'
import { isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

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
        dateRange,
    } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource, updateCompareFilter, setExplicitDate } = useActions(insightVizDataLogic(insightProps))
    const { isTrendsFunnel, isStepsFunnel, isTimeToConvertFunnel, isEmptyFunnel } = useValues(
        funnelDataLogic(insightProps)
    )

    const showCompare =
        (isTrends && display !== ChartDisplayType.ActionsAreaGraph && display !== ChartDisplayType.CalendarHeatmap) ||
        isStickiness
    const showInterval =
        isTrendsFunnel ||
        isLifecycle ||
        ((isTrends || isStickiness) && !(display && NON_TIME_SERIES_DISPLAY_TYPES.includes(display)))
    const showSmoothing =
        isTrends && !isValidBreakdown(breakdownFilter) && (!display || display === ChartDisplayType.ActionsLineGraph)
    const showMultipleYAxesConfig = isTrends || isStickiness
    const showAlertThresholdLinesConfig = isTrends
    const isLineGraph = display === ChartDisplayType.ActionsLineGraph || (!display && isTrendsQuery(querySource))
    const isLinearScale = !yAxisScaleType || yAxisScaleType === 'linear'

    const { showValuesOnSeries, mightContainFractionalNumbers, showConfidenceIntervals, showMovingAverage } = useValues(
        trendsDataLogic(insightProps)
    )

    const advancedOptions: LemonMenuItems = [
        ...((isTrends && display !== ChartDisplayType.CalendarHeatmap) ||
        isRetention ||
        isTrendsFunnel ||
        isStickiness ||
        isLifecycle
            ? [
                  {
                      title: 'Display',
                      items: [
                          ...(isLifecycle ? [{ label: () => <LifecycleStackingFilter /> }] : []),
                          ...(supportsValueOnSeries ? [{ label: () => <ValueOnSeriesFilter /> }] : []),
                          ...(supportsPercentStackView ? [{ label: () => <PercentStackViewFilter /> }] : []),
                          ...(hasLegend ? [{ label: () => <ShowLegendFilter /> }] : []),
                          ...(showAlertThresholdLinesConfig
                              ? [{ label: () => <ShowAlertThresholdLinesFilter /> }]
                              : []),
                          ...(showMultipleYAxesConfig ? [{ label: () => <ShowMultipleYAxesFilter /> }] : []),
                          ...(isTrends || isRetention ? [{ label: () => <ShowTrendLinesFilter /> }] : []),
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
                                              ? 'Moving average is only available for line graphs'
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
        ...((isTrends || isStickiness || isLifecycle) && display !== ChartDisplayType.CalendarHeatmap
            ? [
                  {
                      title: 'Date range',
                      items: [
                          {
                              label: () => (
                                  <LemonSwitch
                                      label="Use exact time range"
                                      className="pb-2"
                                      fullWidth
                                      checked={dateRange?.explicitDate ?? false}
                                      onChange={(checked) => {
                                          setExplicitDate(checked)
                                      }}
                                  />
                              ),
                          },
                      ],
                  },
              ]
            : []),
        ...(isRetention
            ? [
                  {
                      title: 'On dashboards',
                      items: [{ label: () => <RetentionDashboardDisplayPicker /> }],
                  },
              ]
            : []),
    ]
    const advancedOptionsCount: number =
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
        (showMultipleYAxes ? 1 : 0)

    return (
        <div
            className="InsightDisplayConfig flex justify-between items-center flex-wrap gap-2"
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

                {showSmoothing && (
                    <ConfigFilter>
                        <SmoothingFilter />
                    </ConfigFilter>
                )}

                {!!isRetention && (
                    <ConfigFilter>
                        <RetentionDatePicker />
                        {isValidBreakdown(breakdownFilter) && <RetentionBreakdownFilter />}
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
            <div className="flex items-center gap-x-2 flex-wrap">
                {advancedOptions.length > 0 && (
                    <LemonMenu
                        items={advancedOptions}
                        closeOnClickInside={false}
                        placement={isTrendsFunnel ? 'bottom-end' : undefined}
                    >
                        <LemonButton size="small" disabledReason={editingDisabledReason}>
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
