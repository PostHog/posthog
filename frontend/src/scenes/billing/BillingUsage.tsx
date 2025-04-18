import { LemonBanner, LemonButton, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BindLogic } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'

import { GraphType } from '~/types'

import { billingUsageLogic } from './billingUsageLogic'

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

// Define the insightProps with a unique dashboardItemId
const insightProps = {
    dashboardItemId: 'billing-usage',
}

export function BillingUsage(): JSX.Element {
    const logic = billingUsageLogic({ dashboardItemId: 'usage' })
    const { series, dates, filters, dateFrom, dateTo, billingUsageResponseLoading } = useValues(logic)
    const { setFilters, setDateRange } = useActions(logic)

    const handleBreakdownChange = (value: string | null): void => {
        if (!value) {
            setFilters({ breakdowns: undefined })
        } else if (value === 'both') {
            setFilters({ breakdowns: ['type', 'team'] })
        } else {
            setFilters({ breakdowns: [value] })
        }
    }

    return (
        <div className="space-y-4">
            <h2>Usage Details</h2>

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
                <div className="border rounded p-4">
                    <BindLogic logic={insightLogic} props={insightProps}>
                        <LineGraph
                            data-attr="billing-usage-graph"
                            type={GraphType.Line}
                            datasets={series as any}
                            labels={dates}
                            isInProgress={billingUsageResponseLoading}
                            showValuesOnSeries={filters.show_values_on_series}
                            tooltip={{
                                showHeader: true,
                            }}
                            incompletenessOffsetFromEnd={0}
                            labelGroupType="none"
                        />
                    </BindLogic>
                </div>
            )}
        </div>
    )
}
