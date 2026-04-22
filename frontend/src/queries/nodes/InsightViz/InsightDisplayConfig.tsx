import { useValues } from 'kea'
import { ReactNode } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { ChartFilter } from 'lib/components/ChartFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { ResultCustomizationByPicker } from 'scenes/insights/EditorFilters/ResultCustomizationByPicker'
import { ShowTrendLinesFilter } from 'scenes/insights/EditorFilters/ShowTrendLinesFilter'
import { InsightDateFilter } from 'scenes/insights/filters/InsightDateFilter'
import { RetentionChartPicker } from 'scenes/insights/filters/RetentionChartPicker'
import { RetentionDashboardDisplayPicker } from 'scenes/insights/filters/RetentionDashboardDisplayPicker'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { RetentionDatePicker } from 'scenes/insights/RetentionDatePicker'
import { FunnelBinsPicker } from 'scenes/insights/views/Funnels/FunnelBinsPicker'
import { FunnelDisplayLayoutPicker } from 'scenes/insights/views/Funnels/FunnelDisplayLayoutPicker'
import { PathStepPicker } from 'scenes/insights/views/Paths/PathStepPicker'
import { RetentionBreakdownFilter } from 'scenes/retention/RetentionBreakdownFilter'
import { useTrendsOptions } from 'scenes/trends/useTrendsOptions'

import { hasBreakdownFilter } from '~/queries/utils'

function ifShow<T>(condition: boolean | undefined, ...items: T[]): T[] {
    return condition ? items : []
}

export function InsightDisplayConfig(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const {
        isTrends,
        isFunnels,
        isRetention,
        isPaths,
        isStickiness,
        isLifecycle,
        supportsDisplay,
        supportsResultCustomizationBy,
        display,
        breakdownFilter,
        isNonTimeSeriesDisplay,
    } = useValues(insightVizDataLogic(insightProps))
    const { isTrendsFunnel, isStepsFunnel, isTimeToConvertFunnel, isEmptyFunnel } = useValues(
        funnelDataLogic(insightProps)
    )

    const {
        displayItems: trendsDisplayItems,
        dataItems: trendsDataItems,
        displayActiveCount,
        dataActiveCount,
    } = useTrendsOptions()

    const showInterval =
        isTrendsFunnel ||
        isLifecycle ||
        ((isTrends || isStickiness) && !(display && NON_TIME_SERIES_DISPLAY_TYPES.includes(display)))

    // Retention has a small Display section (trend lines only) and one Data section.
    // TODO: extract to useRetentionOptions once other insight types are also extracted.
    const retentionDisplayItems: LemonMenuItems = [
        ...ifShow(isRetention && !isNonTimeSeriesDisplay, { label: () => <ShowTrendLinesFilter /> }),
    ]
    const retentionDataItems: LemonMenuItems = [
        ...ifShow(isRetention, {
            title: 'On dashboards',
            items: [{ label: () => <RetentionDashboardDisplayPicker /> }],
        }),
    ]

    const displayOptions: LemonMenuItems = [
        ...trendsDisplayItems,
        ...ifShow(retentionDisplayItems.length > 0, {
            title: (
                <h5 className="mx-2 my-1" data-attr="options-display-section">
                    Display
                </h5>
            ),
            items: retentionDisplayItems,
        }),
        ...ifShow(supportsResultCustomizationBy, {
            title: (
                <h5 className="mx-2 my-1">
                    Color customization by{' '}
                    <Tooltip title="You can customize the appearance of individual results in your insights. This can be done based on the result's name (e.g., customize the breakdown value 'pizza' for the first series) or based on the result's rank (e.g., customize the first dataset in the results).">
                        <IconInfo className="relative top-0.5 text-lg text-secondary" />
                    </Tooltip>
                </h5>
            ),
            items: [{ label: () => <ResultCustomizationByPicker /> }],
        }),
    ]

    const dataOptions: LemonMenuItems = [...trendsDataItems, ...retentionDataItems]

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
                {displayOptions.length > 0 && (
                    <LemonMenu
                        items={displayOptions}
                        closeOnClickInside={false}
                        placement={isTrendsFunnel ? 'bottom-end' : undefined}
                    >
                        <LemonButton size="small" disabledReason={editingDisabledReason}>
                            <span className="font-medium whitespace-nowrap">
                                Display
                                {displayActiveCount ? (
                                    <span className="ml-0.5 text-secondary ligatures-none">({displayActiveCount})</span>
                                ) : null}
                            </span>
                        </LemonButton>
                    </LemonMenu>
                )}
                {dataOptions.length > 0 && (
                    <LemonMenu
                        items={dataOptions}
                        closeOnClickInside={false}
                        placement={isTrendsFunnel ? 'bottom-end' : undefined}
                    >
                        <LemonButton size="small" disabledReason={editingDisabledReason}>
                            <span className="font-medium whitespace-nowrap">
                                Data
                                {dataActiveCount ? (
                                    <span className="ml-0.5 text-secondary ligatures-none">({dataActiveCount})</span>
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
