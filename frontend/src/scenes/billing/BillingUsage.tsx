import './BillingUsage.scss'

import { LemonCheckbox, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { organizationLogic } from 'scenes/organizationLogic'

import { BillingDataTable } from './BillingDataTable'
import { BillingLineGraph } from './BillingLineGraph'
import { billingUsageLogic } from './billingUsageLogic'
import { USAGE_TYPES } from './constants'

export function BillingUsage(): JSX.Element {
    const logic = billingUsageLogic({ dashboardItemId: 'usage' })
    const {
        series,
        dates,
        filters,
        dateFrom,
        dateTo,
        billingUsageResponseLoading,
        dateOptions,
        excludeEmptySeries,
        finalHiddenSeries,
    } = useValues(logic)
    const { setFilters, setDateRange, toggleSeries, toggleAllSeries, setExcludeEmptySeries, toggleTeamBreakdown } =
        useActions(logic)
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)

    return (
        <div className="space-y-4">
            <div className="flex gap-4 items-start flex-wrap">
                {/* Usage Types */}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Usage Types</LemonLabel>
                    <LemonInputSelect
                        mode="multiple"
                        displayMode="count"
                        bulkActions="select-and-clear-all"
                        className="w-50 h-10"
                        value={filters.usage_types || []}
                        onChange={(value) => setFilters({ usage_types: value })}
                        placeholder="All usage types"
                        options={USAGE_TYPES.map((opt) => ({ key: opt.value, label: opt.label }))}
                        allowCustomValues={false}
                    />
                </div>

                {/* Teams */}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Teams</LemonLabel>
                    <LemonInputSelect
                        mode="multiple"
                        displayMode="count"
                        bulkActions="select-and-clear-all"
                        className="w-50 h-10"
                        value={(filters.team_ids || []).map(String)}
                        onChange={(value) => setFilters({ team_ids: value.map(Number).filter((n) => !isNaN(n)) })}
                        placeholder="All teams"
                        options={
                            currentOrganization?.teams?.map((team) => ({
                                key: String(team.id),
                                label: team.name,
                            })) || []
                        }
                        loading={currentOrganizationLoading}
                        allowCustomValues={false}
                    />
                </div>

                {/* Breakdowns */}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Break down by</LemonLabel>
                    <div className="flex gap-2 items-center min-h-10">
                        <span className="opacity-70">
                            <LemonCheckbox
                                label="Type"
                                checked={true}
                                disabledReason="Breakdown by Type is required for usage volume, as summing different units (e.g., events + recordings) doesn't produce a meaningful total."
                            />
                        </span>
                        <LemonCheckbox
                            label="Team"
                            checked={(filters.breakdowns || []).includes('team')}
                            onChange={toggleTeamBreakdown}
                        />
                    </div>
                </div>

                {/* Date Range */}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Date range (UTC)</LemonLabel>
                    <div className="bg-bg-light rounded-md">
                        <DateFilter
                            className="h-8 flex items-center"
                            dateFrom={dateFrom}
                            dateTo={dateTo}
                            onChange={(fromDate, toDate) => setDateRange(fromDate, toDate)}
                            dateOptions={dateOptions}
                        />
                    </div>
                </div>

                {/* Interval */}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Group by</LemonLabel>
                    <div className="bg-bg-light rounded-md">
                        <LemonSelect
                            className="h-10.5 flex items-center"
                            size="small"
                            value={filters.interval || 'day'}
                            onChange={(value: 'day' | 'week' | 'month') => setFilters({ interval: value })}
                            options={[
                                { value: 'day', label: 'Day' },
                                { value: 'week', label: 'Week' },
                                { value: 'month', label: 'Month' },
                            ]}
                        />
                    </div>
                </div>

                {/* Exclude Empty Series */}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Options</LemonLabel>
                    <div className="flex items-center min-h-10">
                        <LemonCheckbox
                            label="Hide results with no usage"
                            checked={excludeEmptySeries}
                            onChange={setExcludeEmptySeries}
                        />
                    </div>
                </div>
            </div>

            <div className="border rounded p-4 bg-white">
                <BillingLineGraph
                    series={series}
                    dates={dates}
                    isLoading={billingUsageResponseLoading}
                    hiddenSeries={finalHiddenSeries}
                    showLegend={false}
                    interval={filters.interval}
                />
            </div>

            {series.length > 0 && (
                <div className="mt-4">
                    <h3 className="text-lg font-semibold mb-2">Detailed Results</h3>
                    <BillingDataTable
                        series={series}
                        dates={dates}
                        isLoading={billingUsageResponseLoading}
                        hiddenSeries={finalHiddenSeries}
                        toggleSeries={toggleSeries}
                        toggleAllSeries={toggleAllSeries}
                    />
                </div>
            )}
        </div>
    )
}
