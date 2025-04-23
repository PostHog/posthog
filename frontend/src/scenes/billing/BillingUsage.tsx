import './BillingUsage.scss'

import { LemonBanner, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { useState } from 'react'

import { BillingDataTable } from './BillingDataTable'
import { BillingLineGraph } from './BillingLineGraph'
import { billingUsageLogic } from './billingUsageLogic'

const USAGE_TYPES = [
    { label: 'Events', value: 'event_count_in_period' },
    { label: 'Recordings', value: 'recording_count_in_period' },
    { label: 'Feature Flags', value: 'billable_feature_flag_requests_count_in_period' },
    { label: 'Persons', value: 'enhanced_persons_event_count_in_period' },
    { label: 'Month', value: 'month' },
]

type BreakdownOption = { label: string; value: string | null }

const BREAKDOWN_OPTIONS: BreakdownOption[] = [
    { label: 'None', value: null },
    { label: 'By Type', value: 'type' },
    { label: 'By Team', value: 'team' },
    { label: 'By Type & Team', value: 'both' },
]

export function BillingUsage(): JSX.Element {
    const logic = billingUsageLogic({ dashboardItemId: 'usage' })
    const { series, dates, filters, dateFrom, dateTo, billingUsageResponseLoading } = useValues(logic)
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
            setHiddenSeries(series.map((s) => s.id))
        } else {
            // Show all series
            setHiddenSeries([])
        }
    }

    return (
        <div className="space-y-4">
            <div className="flex gap-2 items-center flex-wrap">
                <LemonSelect
                    value={filters.usage_type}
                    options={USAGE_TYPES}
                    onChange={(value) => setFilters({ usage_type: value || undefined })}
                    placeholder="Select usage type"
                    allowClear={true}
                />
                <LemonSelect<string | null>
                    value={filters.breakdowns?.length === 2 ? 'both' : filters.breakdowns?.[0] || null}
                    options={BREAKDOWN_OPTIONS}
                    onChange={handleBreakdownChange}
                    placeholder="Select breakdown"
                />
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={(fromDate, toDate) => setDateRange(fromDate || null, toDate || null)}
                />
            </div>

            {!filters.usage_type && !filters.breakdowns?.includes('type') && (
                <LemonBanner type="info">
                    Please select a usage type or break down by type to see usage data. Unselecting usage type will show
                    all types when you have a breakdown by type.
                </LemonBanner>
            )}

            {(filters.usage_type || filters.breakdowns?.includes('type')) && (
                <>
                    <div className="border rounded p-4 bg-white">
                        <BillingLineGraph
                            series={series}
                            dates={dates}
                            isLoading={billingUsageResponseLoading}
                            hiddenSeries={hiddenSeries}
                            showLegend={false}
                        />
                    </div>

                    {series.length > 0 && (
                        <div className="mt-4">
                            <h3 className="text-lg font-semibold mb-2">Detailed Results</h3>
                            <BillingDataTable
                                series={series}
                                dates={dates}
                                isLoading={billingUsageResponseLoading}
                                hiddenSeries={hiddenSeries}
                                toggleSeries={toggleSeries}
                                toggleAllSeries={toggleAllSeries}
                            />
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
