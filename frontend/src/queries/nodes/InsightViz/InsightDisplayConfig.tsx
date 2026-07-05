import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ChartFilter } from 'lib/components/ChartFilter'
import { ChartFilterNext } from 'lib/components/ChartFilter/ChartFilterNext'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { CompareFilterNext } from 'lib/components/CompareFilter/CompareFilterNext'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { IntervalFilterNext } from 'lib/components/IntervalFilter/IntervalFilterNext'
import { FEATURE_FLAGS, NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { alignResolvedDateRangeToInterval, formatResolvedDateRange } from 'lib/utils/datetime'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { InsightDateFilter } from 'scenes/insights/filters/InsightDateFilter'
import { InsightDateFilterNext } from 'scenes/insights/filters/InsightDateFilter/InsightDateFilterNext'
import { RetentionChartPicker } from 'scenes/insights/filters/RetentionChartPicker'
import { RetentionChartPickerNext } from 'scenes/insights/filters/RetentionChartPickerNext'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { RetentionDatePicker } from 'scenes/insights/RetentionDatePicker'
import { FunnelBinsPicker } from 'scenes/insights/views/Funnels/FunnelBinsPicker'
import { FunnelBinsPickerNext } from 'scenes/insights/views/Funnels/FunnelBinsPickerNext'
import { FunnelDisplayLayoutPicker } from 'scenes/insights/views/Funnels/FunnelDisplayLayoutPicker'
import { FunnelDisplayLayoutPickerNext } from 'scenes/insights/views/Funnels/FunnelDisplayLayoutPickerNext'
import { PathStepPicker } from 'scenes/insights/views/Paths/PathStepPicker'
import { PathStepPickerNext } from 'scenes/insights/views/Paths/PathStepPickerNext'
import { RetentionBreakdownFilter } from 'scenes/retention/RetentionBreakdownFilter'
import { RetentionBreakdownFilterNext } from 'scenes/retention/RetentionBreakdownFilterNext'

import { hasBreakdownFilter, isWebAnalyticsInsightQuery } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { useInsightDisplayOptions } from './insightDisplayOptions'

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
    const { featureFlags } = useValues(featureFlagLogic)
    const funnelsCompareEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_FUNNELS_COMPARE]
    const quillDateFilterEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_DATE_FILTER]

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
        (funnelsCompareEnabled && isFunnels)
    const showInterval =
        isTrendsFunnel ||
        isLifecycle ||
        ((isTrends || isStickiness) && !(display && NON_TIME_SERIES_DISPLAY_TYPES.includes(display)))

    const { items: advancedOptions, count: advancedOptionsCount } = useInsightDisplayOptions()

    const compareFilterProps = {
        compareFilter,
        updateCompareFilter,
        disabled: !canEditInsight || !supportsCompare,
        disableReason: editingDisabledReason,
        tooltip: formatResolvedDateRange(
            alignResolvedDateRangeToInterval(insightData?.resolved_compare_date_range, interval)
        ),
    }

    return (
        <div
            className="InsightDisplayConfig @container flex justify-between items-center flex-wrap gap-2 [&_.LemonButton--small]:[--lemon-button-gap:0.25rem] [&_.LemonButton--small]:[--lemon-button-padding-horizontal:0.375rem]"
            data-attr="insight-filters"
        >
            <div className="flex items-center gap-x-2 flex-wrap gap-y-2">
                {(quillDateFilterEnabled || !isRetention) && (
                    <ConfigFilter>
                        {quillDateFilterEnabled ? (
                            <InsightDateFilterNext disabled={isFunnels && !!isEmptyFunnel} />
                        ) : (
                            <InsightDateFilter disabled={isFunnels && !!isEmptyFunnel} />
                        )}
                    </ConfigFilter>
                )}

                {showInterval && (
                    <ConfigFilter>{quillDateFilterEnabled ? <IntervalFilterNext /> : <IntervalFilter />}</ConfigFilter>
                )}

                {!!isRetention && !quillDateFilterEnabled && (
                    <ConfigFilter>
                        <RetentionDatePicker />
                    </ConfigFilter>
                )}

                {!!isRetention && hasBreakdownFilter(breakdownFilter) && (
                    <ConfigFilter>
                        {quillDateFilterEnabled ? <RetentionBreakdownFilterNext /> : <RetentionBreakdownFilter />}
                    </ConfigFilter>
                )}

                {!!isPaths && (
                    <ConfigFilter>{quillDateFilterEnabled ? <PathStepPickerNext /> : <PathStepPicker />}</ConfigFilter>
                )}

                {showCompare && (
                    <ConfigFilter>
                        {quillDateFilterEnabled ? (
                            <CompareFilterNext {...compareFilterProps} />
                        ) : (
                            <CompareFilter {...compareFilterProps} />
                        )}
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
                    <ConfigFilter>{quillDateFilterEnabled ? <ChartFilterNext /> : <ChartFilter />}</ConfigFilter>
                )}
                {!!isRetention && (
                    <ConfigFilter>
                        {quillDateFilterEnabled ? <RetentionChartPickerNext /> : <RetentionChartPicker />}
                    </ConfigFilter>
                )}
                {!!isStepsFunnel && (
                    <ConfigFilter>
                        {quillDateFilterEnabled ? <FunnelDisplayLayoutPickerNext /> : <FunnelDisplayLayoutPicker />}
                    </ConfigFilter>
                )}
                {!!isTimeToConvertFunnel && (
                    <ConfigFilter>
                        {quillDateFilterEnabled ? <FunnelBinsPickerNext /> : <FunnelBinsPicker />}
                    </ConfigFilter>
                )}
            </div>
        </div>
    )
}

function ConfigFilter({ children }: { children: ReactNode }): JSX.Element {
    return <span className="flex items-center gap-2 text-sm">{children}</span>
}
