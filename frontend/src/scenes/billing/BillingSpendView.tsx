import './BillingUsage.scss' // Keep existing styles for now

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'
// Added TooltipItem
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { useState } from 'react'

import { BillingDataTable } from './BillingDataTable' // Import shared table component
import { BillingLineGraph, BillingSeriesType } from './BillingLineGraph' // Import shared component
import { billingSpendLogic } from './billingSpendLogic' // Use spend logic

// No usage types needed for spend
// const USAGE_TYPES = [...]

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

// Helper function to format currency
const currencyFormatter = (value: number): string => {
    return value.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

// Renamed component to BillingSpendView
export function BillingSpendView(): JSX.Element {
    // Use spend logic
    const logic = billingSpendLogic({ dashboardItemId: 'spendView' }) // Updated key
    // Use spend response loading state
    const { series, dates, filters, dateFrom, dateTo, billingSpendResponseLoading } = useValues(logic)
    const { setFilters, setDateRange } = useActions(logic)
    const [hiddenSeries, setHiddenSeries] = useState<number[]>([])

    const handleBreakdownChange = (value: string | null): void => {
        if (!value) {
            setFilters({ breakdowns: undefined })
        } else if (value === 'both') {
            setFilters({ breakdowns: ['type', 'team'] })
        } else {
            setFilters({ breakdowns: [value] })
        }
    }

    // Function to toggle a series visibility by ID
    const toggleSeries = (id: number): void => {
        setHiddenSeries((prevHidden) =>
            prevHidden.includes(id) ? prevHidden.filter((i) => i !== id) : [...prevHidden, id]
        )
    }

    // Function to toggle all series visibility
    const toggleAllSeries = (): void => {
        if (hiddenSeries.length === 0 && series.length > 0) {
            // Hide all series
            setHiddenSeries(series.map((s: BillingSeriesType) => s.id))
        } else {
            // Show all series
            setHiddenSeries([])
        }
    }

    return (
        <div className="space-y-4">
            <div className="flex gap-2 items-center flex-wrap">
                {/* Removed Usage Type LemonSelect */}
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
                    // TODO: Verify if compare is supported for spend API
                    tooltip="Compare to previous period (if supported)"
                >
                    Compare
                </LemonButton>
            </div>

            {/* Removed banner related to usage type selection */}

            {/* Simplified condition, always show if logic is mounted */}
            <>
                <div className="border rounded p-4 bg-white">
                    {/* Use shared BillingLineGraph component with currency formatter */}
                    <BillingLineGraph
                        series={series}
                        dates={dates}
                        isLoading={billingSpendResponseLoading} // Use spend loading state
                        hiddenSeries={hiddenSeries}
                        valueFormatter={currencyFormatter} // Pass the currency formatter
                    />
                </div>

                {series.length > 0 && (
                    <div className="mt-4">
                        <h3 className="text-lg font-semibold mb-2">Detailed Spend Results</h3> {/* Changed title */}
                        {/* Use shared BillingDataTable component with currency formatter */}
                        <BillingDataTable
                            series={series}
                            dates={dates}
                            isLoading={billingSpendResponseLoading}
                            hiddenSeries={hiddenSeries}
                            toggleSeries={toggleSeries}
                            toggleAllSeries={toggleAllSeries}
                            valueFormatter={currencyFormatter}
                            totalLabel="Total Spend"
                        />
                    </div>
                )}
            </>
        </div>
    )
}
