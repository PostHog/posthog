import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { ChartFilter } from 'lib/components/ChartFilter'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { compareFilterLabel } from 'lib/components/CompareFilter/compareFilterLabel'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { IntervalFilterStandalone } from 'lib/components/IntervalFilter/IntervalFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { NON_TIME_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { dateFilterToText } from 'lib/utils/dateFilters'
import { alignResolvedDateRangeToInterval, formatResolvedDateRange } from 'lib/utils/datetime'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { InsightDateFilter } from 'scenes/insights/filters/InsightDateFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { urls } from 'scenes/urls'

import { hasBreakdownFilter, isWebAnalyticsInsightQuery } from '~/queries/utils'
import { ChartDisplayType, InsightShortId } from '~/types'

import { FunnelBinsPicker } from 'products/product_analytics/frontend/insights/funnels/filters/FunnelBinsPicker'
import { FunnelDisplayLayoutPicker } from 'products/product_analytics/frontend/insights/funnels/filters/FunnelDisplayLayoutPicker'
import { funnelDataLogic } from 'products/product_analytics/frontend/insights/funnels/funnelDataLogic'
import { PathStepPicker } from 'products/product_analytics/frontend/insights/paths/filters/PathStepPicker'
import { RetentionBreakdownFilter } from 'products/product_analytics/frontend/insights/retention/filters/RetentionBreakdownFilter'
import { RetentionChartPicker } from 'products/product_analytics/frontend/insights/retention/filters/RetentionChartPicker'
import { RetentionDatePicker } from 'products/product_analytics/frontend/insights/retention/filters/RetentionDatePicker'
import { InsightFilterOverride } from 'products/product_analytics/frontend/insights/shared/InsightFilterOverride'

import { getBreakdownSummary } from './editorFilterUtils'
import { useInsightDisplayOptions } from './insightDisplayOptions'
import { InsightDisplayOptionsPanel } from './InsightDisplayOptionsPanel'

export function InsightDisplayConfig({ chartTypeControl }: { chartTypeControl?: ReactNode }): JSX.Element {
    const {
        insightProps,
        canEditInsight,
        editingDisabledReason,
        hasOverrides,
        dashboardFilterOverrides,
        dashboardDateOverride,
    } = useValues(insightLogic)

    const {
        querySource,
        dateRange,
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
        filterTestAccountsDefault,
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

    const savedDateLabel = dateFilterToText(dateRange?.date_from, dateRange?.date_to, 'Last 7 days')
    const appliedDateLabel = dashboardDateOverride
        ? dateFilterToText(dashboardDateOverride.dateFrom, dashboardDateOverride.dateTo, 'Last 7 days')
        : null
    const savedTestAccountsExcluded = querySource?.filterTestAccounts ?? filterTestAccountsDefault
    const { tabs: displayOptionTabs, count: advancedOptionsCount } = useInsightDisplayOptions()

    return (
        <div
            className="InsightDisplayConfig @container flex justify-between items-center flex-wrap gap-2 [&_.LemonButton--small]:[--lemon-button-gap:0.25rem] [&_.LemonButton--small]:[--lemon-button-padding-horizontal:0.375rem]"
            data-attr="insight-filters"
        >
            {hasOverrides && insightProps.dashboardItemId && (
                <div className="flex basis-full flex-wrap items-center gap-2 text-sm">
                    <span>Dashboard filters apply to this view. Discard them to edit the saved insight.</span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.insightView(insightProps.dashboardItemId as InsightShortId, insightProps.dashboardId)}
                    >
                        Discard dashboard filters
                    </LemonButton>
                </div>
            )}
            <div className="flex items-start gap-x-2 flex-wrap gap-y-2">
                {dashboardDateOverride ? (
                    <InsightFilterOverride
                        source={dashboardDateOverride.source}
                        savedValue={appliedDateLabel !== savedDateLabel ? savedDateLabel : null}
                    >
                        <DateFilter
                            dateFrom={dashboardDateOverride.dateFrom}
                            dateTo={dashboardDateOverride.dateTo}
                            disabledReason={editingDisabledReason}
                            onChange={(): void => {}}
                        />
                    </InsightFilterOverride>
                ) : (
                    !isRetention && (
                        <ConfigFilter>
                            <InsightDateFilter disabled={isFunnels && !!isEmptyFunnel} />
                        </ConfigFilter>
                    )
                )}

                {showInterval && (
                    <InsightFilterOverride
                        source={dashboardFilterOverrides.interval?.source}
                        savedValue={
                            dashboardFilterOverrides.interval?.value !== interval
                                ? capitalizeFirstLetter(interval || 'day')
                                : null
                        }
                    >
                        {dashboardFilterOverrides.interval ? (
                            <IntervalFilterStandalone
                                interval={dashboardFilterOverrides.interval.value}
                                disabledReason={editingDisabledReason}
                                onIntervalChange={(): void => {}}
                            />
                        ) : (
                            <ConfigFilter>
                                <IntervalFilter />
                            </ConfigFilter>
                        )}
                    </InsightFilterOverride>
                )}

                {!!isRetention && (
                    <ConfigFilter>
                        {!dashboardDateOverride && <RetentionDatePicker />}
                        {hasBreakdownFilter(breakdownFilter) && <RetentionBreakdownFilter />}
                    </ConfigFilter>
                )}

                {!!isPaths && (
                    <ConfigFilter>
                        <PathStepPicker />
                    </ConfigFilter>
                )}

                {showCompare && (
                    <InsightFilterOverride
                        source={dashboardFilterOverrides.compareFilter?.source}
                        savedValue={
                            compareFilterLabel(dashboardFilterOverrides.compareFilter?.value) !==
                            compareFilterLabel(compareFilter)
                                ? compareFilterLabel(compareFilter)
                                : null
                        }
                    >
                        <CompareFilter
                            compareFilter={dashboardFilterOverrides.compareFilter?.value ?? compareFilter}
                            updateCompareFilter={updateCompareFilter}
                            disabled={!canEditInsight || !supportsCompare}
                            disableReason={editingDisabledReason}
                            tooltip={formatResolvedDateRange(
                                alignResolvedDateRangeToInterval(insightData?.resolved_compare_date_range, interval)
                            )}
                        />
                    </InsightFilterOverride>
                )}
                {dashboardFilterOverrides.breakdown && (
                    <InsightFilterOverride
                        source={dashboardFilterOverrides.breakdown.source}
                        savedValue={getBreakdownSummary(breakdownFilter) ?? 'No breakdown'}
                    >
                        <TaxonomicBreakdownFilter
                            insightProps={insightProps}
                            breakdownFilter={dashboardFilterOverrides.breakdown.breakdownFilter}
                            display={display}
                            isTrends={isTrends}
                            isFunnels={isFunnels}
                            disabledReason={editingDisabledReason ?? undefined}
                            updateBreakdownFilter={(): void => {}}
                            updateDisplay={(): void => {}}
                            showLabel={false}
                            size="small"
                        />
                    </InsightFilterOverride>
                )}
                {dashboardFilterOverrides.filterTestAccounts && (
                    <InsightFilterOverride
                        source={dashboardFilterOverrides.filterTestAccounts.source}
                        savedValue={
                            dashboardFilterOverrides.filterTestAccounts.value !== savedTestAccountsExcluded &&
                            (savedTestAccountsExcluded ? 'Excluded' : 'Included')
                        }
                    >
                        <LemonSelect
                            size="small"
                            value={dashboardFilterOverrides.filterTestAccounts.value}
                            disabledReason={editingDisabledReason}
                            options={[
                                { value: true, label: 'Exclude internal and test users' },
                                { value: false, label: 'Include internal and test users' },
                            ]}
                        />
                    </InsightFilterOverride>
                )}
                {dashboardFilterOverrides.propertyGroups.map(({ properties, source }) => (
                    <InsightFilterOverride key={source} source={source}>
                        <PropertyFilters
                            propertyFilters={properties}
                            pageKey={`insight-dashboard-filters-${source}`}
                            onChange={(): void => {}}
                            editable={false}
                            disabledReason={editingDisabledReason ?? undefined}
                            buttonSize="small"
                        />
                    </InsightFilterOverride>
                ))}
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
                {supportsDisplay && <ConfigFilter>{chartTypeControl ?? <ChartFilter />}</ConfigFilter>}
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
