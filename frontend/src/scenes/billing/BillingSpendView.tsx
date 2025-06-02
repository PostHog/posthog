import './BillingUsage.scss'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'
import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { currencyFormatter } from './billing-utils'
import { BillingDataTable } from './BillingDataTable'
import { BillingEarlyAccessBanner } from './BillingEarlyAccessBanner'
import { BillingEmptyState } from './BillingEmptyState'
import { BillingLineGraph } from './BillingLineGraph'
import { BillingNoAccess } from './BillingNoAccess'
import { billingSpendLogic } from './billingSpendLogic'
import { USAGE_TYPES } from './constants'

export function BillingSpendView(): JSX.Element {
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })
    const logic = billingSpendLogic({ dashboardItemId: 'spendView' })
    const {
        series,
        dates,
        filters,
        dateFrom,
        dateTo,
        billingSpendResponseLoading,
        dateOptions,
        excludeEmptySeries,
        finalHiddenSeries,
        heading,
        headingTooltip,
        showSeries,
        showEmptyState,
        teamOptions,
    } = useValues(logic)
    const {
        setFilters,
        setDateRange,
        toggleSeries,
        toggleAllSeries,
        setExcludeEmptySeries,
        toggleBreakdown,
        resetFilters,
    } = useActions(logic)

    if (restrictionReason) {
        return <BillingNoAccess title="Spend" reason={restrictionReason} />
    }

    return (
        <div className="space-y-4">
            <BillingEarlyAccessBanner />
            <div className="border rounded p-4 bg-bg-light space-y-4">
                <div className="flex gap-4 items-start flex-wrap">
                    {/* Products */}
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Products</LemonLabel>
                        <LemonInputSelect
                            mode="multiple"
                            displayMode="count"
                            bulkActions="select-and-clear-all"
                            className="w-50 h-10"
                            value={filters.usage_types || []}
                            onChange={(value: string[]) => setFilters({ usage_types: value })}
                            placeholder="All products"
                            options={USAGE_TYPES.map((opt) => ({ key: opt.value, label: opt.label }))}
                            allowCustomValues={false}
                        />
                    </div>

                    {/* Projects */}
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Projects</LemonLabel>
                        <LemonInputSelect
                            mode="multiple"
                            displayMode="count"
                            bulkActions="select-and-clear-all"
                            className="w-50 h-10"
                            value={(filters.team_ids || []).map(String)}
                            onChange={(value: string[]) =>
                                setFilters({ team_ids: value.map(Number).filter((n: number) => !isNaN(n)) })
                            }
                            placeholder="All projects"
                            options={teamOptions}
                            loading={billingSpendResponseLoading}
                            allowCustomValues={false}
                        />
                    </div>

                    {/* Breakdowns */}
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Break down by</LemonLabel>
                        <div className="flex gap-2 items-center min-h-10">
                            <LemonCheckbox
                                label="Product"
                                checked={filters.breakdowns?.includes('type')}
                                onChange={() => toggleBreakdown('type')}
                            />
                            <LemonCheckbox
                                label="Project"
                                checked={filters.breakdowns?.includes('team')}
                                onChange={() => toggleBreakdown('team')}
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
                                label="Hide results with no spend"
                                checked={excludeEmptySeries}
                                onChange={(value) => setExcludeEmptySeries(value)}
                            />
                        </div>
                    </div>

                    {/* Clear Filters */}
                    <div className="flex flex-col gap-1">
                        <LemonLabel>&nbsp;</LemonLabel>
                        <div className="flex items-center">
                            <LemonButton type="secondary" size="medium" onClick={resetFilters}>
                                Clear filters
                            </LemonButton>
                        </div>
                    </div>
                </div>

                {showSeries && (
                    <BillingLineGraph
                        series={series}
                        dates={dates}
                        isLoading={billingSpendResponseLoading}
                        hiddenSeries={finalHiddenSeries}
                        valueFormatter={currencyFormatter}
                        showLegend={false}
                        interval={filters.interval}
                    />
                )}
                {showEmptyState && (
                    <BillingEmptyState
                        heading="We couldn't find any usage data for your current query."
                        detail="Try adjusting the filters. If you think something is wrong, contact us!"
                    />
                )}
            </div>

            {showSeries && (
                <div className="mt-4 flex flex-col gap-2">
                    <div className="flex items-center gap-1">
                        <h3 className="text-lg font-semibold mb-0">{heading}</h3>
                        {headingTooltip && (
                            <Tooltip title={headingTooltip}>
                                <IconInfo className="text-lg text-secondary shrink-0" />
                            </Tooltip>
                        )}
                    </div>

                    <BillingDataTable
                        series={series}
                        dates={dates}
                        isLoading={billingSpendResponseLoading}
                        hiddenSeries={finalHiddenSeries}
                        toggleSeries={toggleSeries}
                        toggleAllSeries={toggleAllSeries}
                        valueFormatter={currencyFormatter}
                        totalLabel="Total Spend"
                    />
                </div>
            )}
        </div>
    )
}
