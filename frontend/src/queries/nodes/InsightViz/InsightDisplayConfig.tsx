import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ChartFilter } from 'lib/components/ChartFilter'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { alignResolvedDateRangeToInterval, formatResolvedDateRange } from 'lib/utils/datetime'
import { InsightDateFilter } from 'scenes/insights/filters/InsightDateFilter'
import { RetentionChartPicker } from 'scenes/insights/filters/RetentionChartPicker'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { RetentionDatePicker } from 'scenes/insights/RetentionDatePicker'
import { PathStepPicker } from 'scenes/insights/views/Paths/PathStepPicker'

import { hasBreakdownFilter, isWebAnalyticsInsightQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { FunnelBinsPicker } from 'products/product_analytics/frontend/insights/funnels/filters/FunnelBinsPicker'
import { FunnelDisplayLayoutPicker } from 'products/product_analytics/frontend/insights/funnels/filters/FunnelDisplayLayoutPicker'
import { funnelDataLogic } from 'products/product_analytics/frontend/insights/funnels/funnelDataLogic'
import { RetentionBreakdownFilter } from 'products/product_analytics/frontend/insights/retention/filters/RetentionBreakdownFilter'

import { useInsightDisplayOptions } from './insightDisplayOptions'
import { InsightDisplayOptionsPanel } from './InsightDisplayOptionsPanel'

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
        compareFilter,
        supportsCompare,
        interval,
        insightData,
    } = useValues(insightVizDataLogic(insightProps))
    const { updateCompareFilter } = useActions(insightVizDataLogic(insightProps))
    const { isTrendsFunnel, isStepsFunnel, isTimeToConvertFunnel, isEmptyFunnel } = useValues(
        funnelDataLogic(insightProps)
    )
    const isMetric = display === ChartDisplayType.Metric
    // The slope graph shows the first vs last interval, so it drops the options that need the points
    // between them (compare, smoothing, multiple axes, alert/annotation overlays, statistical analysis).
    const isSlopeGraph = display === ChartDisplayType.SlopeGraph
    const showCompare =
        (isTrends &&
            display !== ChartDisplayType.ActionsAreaGraph &&
            display !== ChartDisplayType.CalendarHeatmap &&
            display !== ChartDisplayType.BoxPlot &&
            !isMetric &&
            !isSlopeGraph) ||
        isStickiness ||
        isWebAnalyticsInsightQuery(querySource) ||
        isFunnels
    const showInterval =
        isTrendsFunnel ||
        isLifecycle ||
        ((isTrends || isStickiness) && !(display && NON_TIME_SERIES_DISPLAY_TYPES.includes(display)))

    const { tabs: displayOptionTabs, count: advancedOptionsCount } = useInsightDisplayOptions()

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
                            tooltip={formatResolvedDateRange(
                                alignResolvedDateRangeToInterval(insightData?.resolved_compare_date_range, interval)
                            )}
                        />
                    </ConfigFilter>
                )}
            </div>
            <div className="flex items-center gap-x-2">
                {displayOptionTabs.length > 0 && (
                    <>
                        <LemonDropdown
                            overlay={<InsightDisplayOptionsPanel tabs={displayOptionTabs} />}
                            closeOnClickInside={false}
                            placement="bottom-end"
                        >
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
                        </LemonDropdown>
                        <LemonDropdown
                            overlay={<InsightDisplayOptionsPanel tabs={displayOptionTabs} />}
                            closeOnClickInside={false}
                            placement="bottom-end"
                        >
                            <LemonButton
                                size="small"
                                disabledReason={editingDisabledReason}
                                icon={<IconEllipsis />}
                                aria-label="Options"
                                className="hidden @max-[780px]:flex order-[999]"
                            />
                        </LemonDropdown>
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
    return <span className="flex items-center gap-x-2 text-sm">{children}</span>
}
