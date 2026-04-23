import { useValues } from 'kea'
import { ReactNode } from 'react'

import { ChartFilter } from 'lib/components/ChartFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { InsightDateFilter } from 'scenes/insights/filters/InsightDateFilter'
import { RetentionChartPicker } from 'scenes/insights/filters/RetentionChartPicker'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { RetentionDatePicker } from 'scenes/insights/RetentionDatePicker'
import { FunnelBinsPicker } from 'scenes/insights/views/Funnels/FunnelBinsPicker'
import { FunnelDisplayLayoutPicker } from 'scenes/insights/views/Funnels/FunnelDisplayLayoutPicker'
import { PathStepPicker } from 'scenes/insights/views/Paths/PathStepPicker'
import { RetentionBreakdownFilter } from 'scenes/retention/RetentionBreakdownFilter'

import { hasBreakdownFilter } from '~/queries/utils'

export function InsightDisplayConfig(): JSX.Element {
    const { insightProps } = useValues(insightLogic)

    const {
        isTrends,
        isFunnels,
        isRetention,
        isPaths,
        isStickiness,
        isLifecycle,
        supportsDisplay,
        display,
        breakdownFilter,
    } = useValues(insightVizDataLogic(insightProps))
    const { isTrendsFunnel, isStepsFunnel, isTimeToConvertFunnel, isEmptyFunnel } = useValues(
        funnelDataLogic(insightProps)
    )

    const showInterval =
        isTrendsFunnel ||
        isLifecycle ||
        ((isTrends || isStickiness) && !(display && NON_TIME_SERIES_DISPLAY_TYPES.includes(display)))

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
            </div>
            <div className="flex items-center gap-x-2 flex-wrap">
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
