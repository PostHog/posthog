import { ReactNode } from 'react'
import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightDisplayConfigLogic } from './insightDisplayConfigLogic'

import { InsightDateFilter } from 'scenes/insights/filters/InsightDateFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { RetentionDatePicker } from 'scenes/insights/RetentionDatePicker'
import { RetentionReferencePicker } from 'scenes/insights/filters/RetentionReferencePicker'
import { PathStepPicker } from 'scenes/insights/views/Paths/PathStepPicker'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { ChartFilter } from 'lib/components/ChartFilter'
import { FunnelDisplayLayoutPicker } from 'scenes/insights/views/Funnels/FunnelDisplayLayoutPicker'
import { FunnelBinsPicker } from 'scenes/insights/views/Funnels/FunnelBinsPicker'
import { ValueOnSeriesFilter } from 'scenes/insights/EditorFilters/ValueOnSeriesFilter'
import { PercentStackViewFilter } from 'scenes/insights/EditorFilters/PercentStackViewFilter'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { LemonButton } from '@posthog/lemon-ui'
import { axisLabel } from 'scenes/insights/aggregationAxisFormat'
import { ChartDisplayType } from '~/types'
import { ShowLegendFilter } from 'scenes/insights/EditorFilters/ShowLegendFilter'

export function InsightDisplayConfig(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const {
        showDateRange,
        disableDateRange,
        showCompare,
        showValueOnSeries,
        showPercentStackView,
        showUnit,
        showChart,
        showInterval,
        showSmoothing,
        showRetention,
        showPaths,
        showFunnelDisplayLayout,
        showFunnelBins,
        display,
        trendsFilter,
        hasLegend,
        showLegend,
    } = useValues(insightDisplayConfigLogic(insightProps))

    const { showPercentStackView: isPercentStackViewOn, showValueOnSeries: isValueOnSeriesOn } = useValues(
        trendsDataLogic(insightProps)
    )

    const advancedOptions: LemonMenuItems = [
        ...(showValueOnSeries || showPercentStackView || hasLegend
            ? [
                  {
                      title: 'Display',
                      items: [
                          ...(showValueOnSeries ? [{ label: () => <ValueOnSeriesFilter /> }] : []),
                          ...(showPercentStackView ? [{ label: () => <PercentStackViewFilter /> }] : []),
                          ...(hasLegend ? [{ label: () => <ShowLegendFilter /> }] : []),
                      ],
                  },
              ]
            : []),
        ...(!isPercentStackViewOn && showUnit
            ? [
                  {
                      title: axisLabel(display || ChartDisplayType.ActionsLineGraph),
                      items: [{ label: () => <UnitPicker /> }],
                  },
              ]
            : []),
    ]
    const advancedOptionsCount: number =
        (showValueOnSeries && isValueOnSeriesOn ? 1 : 0) +
        (showPercentStackView && isPercentStackViewOn ? 1 : 0) +
        (!isPercentStackViewOn &&
        showUnit &&
        trendsFilter?.aggregation_axis_format &&
        trendsFilter.aggregation_axis_format !== 'numeric'
            ? 1
            : 0) +
        (hasLegend && showLegend ? 1 : 0)

    return (
        <div className="flex justify-between items-center flex-wrap" data-attr="insight-filters">
            <div className="flex items-center gap-x-2 flex-wrap my-2 gap-y-2">
                {showDateRange && (
                    <ConfigFilter>
                        <InsightDateFilter disabled={disableDateRange} />
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

                {showRetention && (
                    <ConfigFilter>
                        <RetentionDatePicker />
                        <RetentionReferencePicker />
                    </ConfigFilter>
                )}

                {showPaths && (
                    <ConfigFilter>
                        <PathStepPicker />
                    </ConfigFilter>
                )}

                {showCompare && (
                    <ConfigFilter>
                        <CompareFilter />
                    </ConfigFilter>
                )}
            </div>
            <div className="flex items-center gap-x-2 flex-wrap my-2">
                {advancedOptions.length > 0 && (
                    <LemonMenu items={advancedOptions} closeOnClickInside={false}>
                        <LemonButton size="small" status="stealth">
                            <span className="font-medium whitespace-nowrap">
                                Options{advancedOptionsCount ? ` (${advancedOptionsCount})` : null}
                            </span>
                        </LemonButton>
                    </LemonMenu>
                )}
                {showChart && (
                    <ConfigFilter>
                        <ChartFilter />
                    </ConfigFilter>
                )}
                {showFunnelDisplayLayout && (
                    <ConfigFilter>
                        <FunnelDisplayLayoutPicker />
                    </ConfigFilter>
                )}
                {showFunnelBins && (
                    <ConfigFilter>
                        <FunnelBinsPicker />
                    </ConfigFilter>
                )}
            </div>
        </div>
    )
}

function ConfigFilter({ children }: { children: ReactNode }): JSX.Element {
    return <span className="space-x-2 flex items-center text-sm">{children}</span>
}
