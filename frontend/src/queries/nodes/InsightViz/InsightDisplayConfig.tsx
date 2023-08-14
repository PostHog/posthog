import { PropsWithChildren, ReactNode } from 'react'
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

interface InsightDisplayConfigProps {
    disableTable: boolean
}

export function InsightDisplayConfig({ disableTable }: InsightDisplayConfigProps): JSX.Element {
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
        compare,
        trendsFilter,
        hasLegend,
    } = useValues(insightDisplayConfigLogic(insightProps))

    const { showPercentStackView: isPercentStackViewOn, showValueOnSeries: isValueOnSeriesOn } = useValues(
        trendsDataLogic(insightProps)
    )

    const advancedOptions: LemonMenuItems = [
        ...(showCompare || showValueOnSeries || showPercentStackView
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
        (showCompare && compare ? 1 : 0) +
        (showValueOnSeries && isValueOnSeriesOn ? 1 : 0) +
        (showPercentStackView && isPercentStackViewOn ? 1 : 0) +
        (!isPercentStackViewOn &&
        showUnit &&
        trendsFilter?.aggregation_axis_format &&
        trendsFilter.aggregation_axis_format !== 'numeric'
            ? 1
            : 0) +
        (hasLegend && trendsFilter?.show_legend ? 1 : 0)

    return (
        <div className="flex justify-between items-center flex-wrap" data-attr="insight-filters">
            <div className="flex items-center space-x-2 flex-wrap my-2 gap-y-2">
                {showDateRange && !disableTable && (
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
            <div className="flex items-center space-x-4 flex-wrap my-2 grow justify-end">
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
                {advancedOptions.length > 0 && (
                    <LemonMenu items={advancedOptions} closeOnClickInside={false}>
                        <LemonButton size="small" status="stealth">
                            <span className="font-medium">
                                Options
                                {advancedOptionsCount ? (
                                    <>
                                        &nbsp;<span className="text-muted">({advancedOptionsCount})</span>
                                    </>
                                ) : null}
                            </span>
                        </LemonButton>
                    </LemonMenu>
                )}
            </div>
        </div>
    )
}

function ConfigFilter(props: PropsWithChildren<ReactNode>): JSX.Element {
    return <span className="space-x-2 flex items-center text-sm">{props.children}</span>
}
