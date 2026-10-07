import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconCalendar } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { dateMapping } from 'lib/utils/dateFilters'

import { HomeTabExplore } from 'products/product_analytics/frontend/insights/home/HomeTabExplore'

import { HomeTabChartCard } from './HomeTabChartCard'
import { homeTabDefaultLogic } from './homeTabDefaultLogic'
import { getHomeTabAudienceOptions, getHomeTabBreakdownOptions, getHomeTabChartOptions } from './homeTabDefaultTiles'
import { HomeTabStatTiles } from './HomeTabStatTiles'

const HOME_DATE_OPTIONS = dateMapping.filter((option) => option.key !== CUSTOM_OPTION_KEY)

export function HomeTabDefault({ dashboardActions }: { dashboardActions?: ReactNode }): JSX.Element {
    const { dateRange, compare, selectedMetric, selectedContentKey } = useValues(homeTabDefaultLogic)
    const { setDates, setCompare, setSelectedMetric, setSelectedContentKey } = useActions(homeTabDefaultLogic)

    const metricCharts = getHomeTabChartOptions(dateRange, compare)
    const audienceCharts = getHomeTabAudienceOptions(dateRange)
    const breakdownCharts = getHomeTabBreakdownOptions(dateRange)
    const primaryChart = metricCharts.find((option) => option.key === selectedMetric) ?? metricCharts[0]
    const retentionChart =
        metricCharts.find((option) => option.key === 'retention') ?? metricCharts[metricCharts.length - 1]
    const contentChart = breakdownCharts.find((option) => option.key === selectedContentKey) ?? breakdownCharts[0]
    const eventsChart =
        breakdownCharts.find((option) => option.key === 'top_events') ?? breakdownCharts[breakdownCharts.length - 1]

    return (
        <div className="@container/home-overview flex flex-col gap-4 @max-[32rem]/saved-insights:gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-primary pb-2 @min-[32rem]/home-overview:pb-3">
                <div className="flex w-full items-center justify-between gap-2 @min-[48rem]/home-overview:w-auto">
                    <h2 className="m-0 min-w-0 text-lg font-semibold">
                        <span className="hidden @min-[32rem]/home-overview:inline">Product Analytics </span>
                        <span>Overview</span>
                    </h2>
                    <div className="shrink-0 whitespace-nowrap @min-[48rem]/saved-insights:hidden">
                        {dashboardActions}
                    </div>
                </div>
                <div className="home-tab-date-controls grid w-full min-w-0 grid-cols-2 gap-2 [&_.LemonButton]:h-full [&_.LemonButton__content]:truncate @max-[32rem]/home-overview:[&_.LemonButton__content]:text-xs @min-[48rem]/home-overview:flex @min-[48rem]/home-overview:w-auto @min-[48rem]/home-overview:flex-wrap">
                    <div className="min-w-0 [&_.LemonButton]:w-full @min-[48rem]/home-overview:[&_.LemonButton]:w-auto">
                        <DateFilter
                            showCustom
                            showExplicitDateToggle
                            dateFrom={dateRange.date_from}
                            dateTo={dateRange.date_to}
                            explicitDate={dateRange.explicitDate ?? false}
                            dateOptions={HOME_DATE_OPTIONS}
                            onChange={setDates}
                            makeLabel={(label) => (
                                <span className="flex items-center gap-1.5">
                                    <IconCalendar />
                                    <span>{label}</span>
                                </span>
                            )}
                        />
                    </div>
                    <div className="min-w-0 [&_.LemonSelect]:w-full [&_.LemonButton]:w-full @min-[48rem]/home-overview:[&_.LemonSelect]:w-auto @min-[48rem]/home-overview:[&_.LemonButton]:w-auto">
                        <CompareFilter
                            compareFilter={{ compare }}
                            updateCompareFilter={(filter) => setCompare(!!filter.compare)}
                            allowCustomComparison={false}
                        />
                    </div>
                </div>
            </div>

            <HomeTabStatTiles
                dateRange={dateRange}
                compare={compare}
                selectedKey={selectedMetric}
                onSelect={setSelectedMetric}
            />

            <HomeTabChartCard
                key={primaryChart.key}
                option={primaryChart}
                size="primary"
                source="Pageviews and screen views"
            />

            <section className="flex flex-col gap-3" aria-label="What people do">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h2 className="m-0 text-base font-semibold">What people do</h2>
                    <span className="text-xs text-secondary">Most common content and events in this period</span>
                </div>
                <div className="grid min-w-0 grid-cols-1 gap-3 @min-[44rem]/home-overview:grid-cols-2">
                    <HomeTabChartCard
                        key={contentChart.key}
                        option={contentChart}
                        size="ranking"
                        source={selectedContentKey === 'top_pages' ? 'Pageviews' : 'Screen views'}
                        control={
                            <LemonSelect
                                size="small"
                                value={selectedContentKey}
                                onChange={(value) => value && setSelectedContentKey(value)}
                                options={[
                                    { value: 'top_pages', label: 'Pages' },
                                    { value: 'top_screens', label: 'Screens' },
                                ]}
                                dropdownMatchSelectWidth={false}
                                data-attr="home-tab-content-chart"
                            />
                        }
                    />
                    <HomeTabChartCard option={eventsChart} size="ranking" source="Captured events" />
                </div>
            </section>

            <section className="flex flex-col gap-3" aria-label="Your audience">
                <h2 className="m-0 text-base font-semibold">Your audience</h2>
                <div className="grid min-w-0 grid-cols-1 gap-3 @min-[56rem]/home-overview:grid-cols-[2fr_1fr]">
                    {audienceCharts.map((option) => (
                        <HomeTabChartCard
                            key={option.key}
                            option={option}
                            size="supporting"
                            source="Pageviews and screen views"
                        />
                    ))}
                </div>
            </section>

            <div className="grid min-w-0 grid-cols-1 gap-3 @min-[44rem]/home-overview:grid-cols-2">
                <HomeTabChartCard option={retentionChart} size="supporting" source="Pageviews" />
                <HomeTabExplore />
            </div>
        </div>
    )
}
