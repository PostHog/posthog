import './BillingUsage5.scss'

import { LemonBanner, LemonButton, LemonCheckbox, LemonSelect } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dayjs } from 'lib/dayjs'
import { useEffect, useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'

import { ChartDisplayType, GraphDataset, GraphType, InsightLogicProps, InsightType } from '~/types'

import { billingUsageLogic } from './billingUsageLogic'

// Define a simple context type that matches what we need
interface BillingContext {
    emptyStateHeading?: string
    emptyStateDetail?: string
    groupTypeLabel?: string
}

const USAGE_TYPES = [
    { label: 'Events', value: 'event_count_in_period' },
    { label: 'Recordings', value: 'recording_count_in_period' },
    { label: 'Feature Flags', value: 'billable_feature_flag_requests_count_in_period' },
    { label: 'Persons', value: 'enhanced_persons_event_count_in_period' },
]

type BreakdownOption = { label: string; value: string | null }

const BREAKDOWN_OPTIONS: BreakdownOption[] = [
    { label: 'None', value: null },
    { label: 'By Type', value: 'type' },
    { label: 'By Team', value: 'team' },
    { label: 'By Type & Team', value: 'both' },
]

const INTERVAL_OPTIONS = [
    { label: 'Day', value: 'day' },
    { label: 'Week', value: 'week' },
    { label: 'Month', value: 'month' },
]

// Maximum number of date columns to show
const MAX_DATE_COLUMNS = 8

// Define the insightProps with a unique dashboardItemId
const INSIGHT_PROPS: InsightLogicProps = {
    dashboardItemId: 'new-billing-usage-5',
}

// Component for color dot with the correct color
function SeriesColorDot({ colorIndex }: { colorIndex: number }): JSX.Element {
    // Get the color based on index
    return <div className={`series-color-dot series-color-dot-${colorIndex % 10}`} />
}

export function BillingUsage5(): JSX.Element {
    const logic = billingUsageLogic({ dashboardItemId: 'billing-usage-5' })
    const { series, dates, filters, dateFrom, dateTo, billingUsageResponseLoading, billingUsageResponse } =
        useValues(logic)
    const { setFilters, setDateRange } = useActions(logic)
    const [hiddenSeries, setHiddenSeries] = useState<number[]>([])
    const [dataLoaded, setDataLoaded] = useState(false)

    // Function to toggle a series visibility
    const toggleSeries = (seriesIndex: number): void => {
        setHiddenSeries((prevHidden) =>
            prevHidden.includes(seriesIndex)
                ? prevHidden.filter((i) => i !== seriesIndex)
                : [...prevHidden, seriesIndex]
        )
    }

    // Filter series based on hidden state
    const getVisibleSeries = (allSeries: any[]): any[] => {
        return allSeries.filter((_, index) => !hiddenSeries.includes(index))
    }

    // Connect to insight logics
    const { setInsightData } = useActions(insightVizDataLogic(INSIGHT_PROPS))

    // Transform billing data to insight format and update the insight
    useEffect(() => {
        if (billingUsageResponse?.results && billingUsageResponse.results.length > 0) {
            // Set the insight data from billing usage response
            const transformedData = {
                result: billingUsageResponse.results.map((result) => ({
                    ...result,
                    // Make sure each series has necessary properties for InsightsTable
                    persons_urls: Array(result.data.length).fill({ url: '#' }),
                    persons: Array(result.data.length).fill([]),
                })),
                filters: {
                    insight: InsightType.TRENDS,
                    interval: filters.interval || 'day',
                    display: ChartDisplayType.ActionsLineGraph,
                },
            }

            // Feed the data to the insight system
            setInsightData(transformedData)
            setDataLoaded(true)
        }
    }, [billingUsageResponse, filters.interval, setInsightData])

    const handleBreakdownChange = (value: string | null): void => {
        if (!value) {
            setFilters({ breakdowns: undefined })
        } else if (value === 'both') {
            setFilters({ breakdowns: ['type', 'team'] })
        } else {
            setFilters({ breakdowns: [value] })
        }
    }

    // Create a context to pass to visualization components
    const context: BillingContext = {
        emptyStateHeading: 'No usage data',
        emptyStateDetail: 'Please select a usage type or breakdown to see data',
        groupTypeLabel: 'users',
    }

    const renderGraph = (): JSX.Element | null => {
        if (!series || series.length === 0) {
            if (billingUsageResponseLoading) {
                return <div className="text-center p-10">Loading...</div>
            }
            return <div className="text-center p-10">No data to display</div>
        }

        // Get visible series
        const visibleSeries = getVisibleSeries(series)

        // Following the pattern from BillingUsage.tsx to wrap LineGraph with BindLogic
        return (
            <BindLogic logic={insightLogic} props={INSIGHT_PROPS}>
                <LineGraph
                    data-attr="billing-usage-graph"
                    type={GraphType.Line}
                    datasets={visibleSeries as any as GraphDataset[]}
                    labels={dates}
                    isInProgress={false}
                    tooltip={{
                        showHeader: true,
                        groupTypeLabel: context.groupTypeLabel,
                    }}
                    labelGroupType="none"
                    showValuesOnSeries={filters.show_values_on_series}
                    incompletenessOffsetFromEnd={0}
                />
            </BindLogic>
        )
    }

    const renderTable = (): JSX.Element | null => {
        if (!dataLoaded || !series || series.length === 0 || !dates.length) {
            return null
        }

        // Calculate which dates to show
        // For limited screen space, show a selection of dates with focus on most recent
        const datesToShow = [...dates]
        if (datesToShow.length > MAX_DATE_COLUMNS) {
            // Keep most recent MAX_DATE_COLUMNS-2 dates, and add the first date
            datesToShow.splice(1, datesToShow.length - MAX_DATE_COLUMNS + 1)
        }

        // Format dates for display
        const formattedDates = datesToShow.map((date) => {
            try {
                return typeof date === 'string' ? dayjs(date).format('MMM D, YYYY') : 'Unknown'
            } catch (e) {
                return 'Unknown'
            }
        })

        // Find the data indices that match our dates to display
        const dateIndices = datesToShow.map((dateToShow) => dates.indexOf(dateToShow))

        return (
            <div className="rounded border bg-white overflow-x-auto">
                <table className="w-full min-w-full">
                    <thead>
                        <tr className="border-b bg-bg-light">
                            <th className="p-2 text-left whitespace-nowrap w-64">Series</th>
                            {formattedDates.map((date, i) => (
                                <th key={`date-${i}`} className="p-2 text-right whitespace-nowrap">
                                    {date}
                                </th>
                            ))}
                            <th className="p-2 text-right whitespace-nowrap">Total</th>
                        </tr>
                    </thead>
                    <tbody>
                        {series.map((item, index) => {
                            const isHidden = hiddenSeries.includes(index)

                            return (
                                <tr
                                    key={item.id || index}
                                    className={`border-b hover:bg-bg-light cursor-pointer ${
                                        isHidden ? 'opacity-50' : ''
                                    }`}
                                >
                                    <td className="p-2 flex items-center">
                                        <div
                                            className="flex items-center cursor-pointer"
                                            onClick={(e) => {
                                                e.stopPropagation()
                                                toggleSeries(index)
                                            }}
                                        >
                                            <LemonCheckbox
                                                checked={!isHidden}
                                                onChange={() => toggleSeries(index)}
                                                className="mr-2"
                                            />
                                            <SeriesColorDot colorIndex={index} />
                                            <span className="font-medium">{item.label}</span>
                                        </div>
                                    </td>

                                    {dateIndices.map((dateIndex, i) => (
                                        <td key={`val-${index}-${i}`} className="p-2 text-right whitespace-nowrap">
                                            {dateIndex >= 0 && dateIndex < item.data.length
                                                ? item.data[dateIndex].toLocaleString()
                                                : 0}
                                        </td>
                                    ))}

                                    <td className="p-2 text-right font-medium whitespace-nowrap">
                                        {(item.count || item.data.reduce((sum, val) => sum + val, 0)).toLocaleString()}
                                    </td>
                                </tr>
                            )
                        })}
                    </tbody>
                </table>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <h2>Usage Details (Insight-based)</h2>

            <div className="flex gap-2 items-center flex-wrap">
                <LemonSelect
                    value={filters.usage_type}
                    options={USAGE_TYPES}
                    onChange={(value) => setFilters({ usage_type: value })}
                    placeholder="Select usage type"
                />
                <LemonSelect<string | null>
                    value={filters.breakdowns?.length === 2 ? 'both' : filters.breakdowns?.[0] || null}
                    options={BREAKDOWN_OPTIONS}
                    onChange={handleBreakdownChange}
                    placeholder="Select breakdown"
                />
                <LemonSelect
                    value={filters.interval || 'day'}
                    options={INTERVAL_OPTIONS}
                    onChange={(value) => setFilters({ interval: value as 'day' | 'week' | 'month' })}
                />
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={(fromDate, toDate) => setDateRange(fromDate || null, toDate || null)}
                />
                <LemonButton
                    type="secondary"
                    onClick={() => setFilters({ compare: filters.compare ? undefined : 'previous_period' })}
                    active={!!filters.compare}
                >
                    Compare
                </LemonButton>
            </div>

            {!filters.usage_type && !filters.breakdowns?.includes('type') && (
                <LemonBanner type="info">
                    Please select a usage type or break down by type to see usage data
                </LemonBanner>
            )}

            {(filters.usage_type || filters.breakdowns?.includes('type')) && (
                <>
                    <div className="border rounded p-4 bg-white">{renderGraph()}</div>

                    <div className="mt-4">
                        <h3 className="text-lg font-semibold mb-2">Detailed Results</h3>
                        {renderTable()}
                    </div>
                </>
            )}
        </div>
    )
}
