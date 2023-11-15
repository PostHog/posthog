import { ReactNode } from 'react'
import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

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
import { FEATURE_FLAGS, NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export function InsightDisplayConfig(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const {
        isTrends,
        isFunnels,
        isRetention,
        isPaths,
        isStickiness,
        isLifecycle,
        supportsDisplay,
        display,
        breakdown,
        trendsFilter,
        hasLegend,
        showLegend,
        supportsValueOnSeries,
        showPercentStackView,
    } = useValues(insightVizDataLogic(insightProps))
    const { isTrendsFunnel, isStepsFunnel, isTimeToConvertFunnel, isEmptyFunnel } = useValues(
        funnelDataLogic(insightProps)
    )

    const showCompare = (isTrends && display !== ChartDisplayType.ActionsAreaGraph) || isStickiness
    const showInterval =
        isTrendsFunnel ||
        isLifecycle ||
        ((isTrends || isStickiness) && !(display && NON_TIME_SERIES_DISPLAY_TYPES.includes(display)))
    const showSmoothing =
        isTrends &&
        !breakdown?.breakdown_type &&
        !trendsFilter?.compare &&
        (!display || display === ChartDisplayType.ActionsLineGraph) &&
        featureFlags[FEATURE_FLAGS.SMOOTHING_INTERVAL]

    const { showPercentStackView: isPercentStackViewOn, showValueOnSeries } = useValues(trendsDataLogic(insightProps))

    const advancedOptions: LemonMenuItems = [
        ...(supportsValueOnSeries || showPercentStackView || hasLegend
            ? [
                  {
                      title: 'Display',
                      items: [
                          ...(supportsValueOnSeries ? [{ label: () => <ValueOnSeriesFilter /> }] : []),
                          ...(showPercentStackView ? [{ label: () => <PercentStackViewFilter /> }] : []),
                          ...(hasLegend ? [{ label: () => <ShowLegendFilter /> }] : []),
                      ],
                  },
              ]
            : []),
        ...(!isPercentStackViewOn && isTrends
            ? [
                  {
                      title: axisLabel(display || ChartDisplayType.ActionsLineGraph),
                      items: [{ label: () => <UnitPicker /> }],
                  },
              ]
            : []),
    ]
    const advancedOptionsCount: number =
        (supportsValueOnSeries && showValueOnSeries ? 1 : 0) +
        (showPercentStackView && isPercentStackViewOn ? 1 : 0) +
        (!isPercentStackViewOn &&
        isTrends &&
        trendsFilter?.aggregation_axis_format &&
        trendsFilter.aggregation_axis_format !== 'numeric'
            ? 1
            : 0) +
        (hasLegend && showLegend ? 1 : 0)

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
                        <RetentionReferencePicker />
                    </ConfigFilter>
                )}

                {!!isPaths && (
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
            <div className="flex items-center gap-x-2 flex-wrap">
                {advancedOptions.length > 0 && (
                    <LemonMenu items={advancedOptions} closeOnClickInside={false}>
                        <LemonButton size="small" status="stealth">
                            <span className="font-medium whitespace-nowrap">
                                Options{advancedOptionsCount ? ` (${advancedOptionsCount})` : null}
                            </span>
                        </LemonButton>
                    </LemonMenu>
                )}
                {supportsDisplay && (
                    <ConfigFilter>
                        <ChartFilter />
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
    return <span className="space-x-2 flex items-center text-sm">{children}</span>
}
