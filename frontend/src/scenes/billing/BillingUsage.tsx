import './BillingUsage.scss'

import { useActions, useValues } from 'kea'

import { IconChevronDown, IconInfo } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSelect, LemonMenu, LemonInput } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { billingErrorGuidance, getUsageTypeOptions, selectionCoversEveryProject } from './billing-utils'
import { BillingChart } from './BillingChart'
import { BillingDataTable } from './BillingDataTable'
import { BillingEarlyAccessBanner } from './BillingEarlyAccessBanner'
import { BillingEmptyState } from './BillingEmptyState'
import { billingLogic } from './billingLogic'
import { BillingNoAccess } from './BillingNoAccess'
import { billingUsageLogic } from './billingUsageLogic'
import { TOP_PROJECTS_OPTIONS } from './constants'
import type { BillingChartType } from './types'

export function BillingUsage(): JSX.Element {
    const { minimumUsageSpendReadAccessLevel } = useValues(billingLogic)
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: minimumUsageSpendReadAccessLevel,
        scope: RestrictionScope.Organization,
    })
    const logic = billingUsageLogic({ syncWithUrl: true })
    const {
        series,
        dates,
        filters,
        dateFrom,
        dateTo,
        billingUsageResponseLoading,
        billingUsageError,
        dateOptions,
        excludeEmptySeries,
        finalHiddenSeries,
        heading,
        headingTooltip,
        showSeries,
        showEmptyState,
        teamOptions,
        teamIdOptionsLoading,
        billingPeriodMarkers,
        usageExportUrl,
        usageChartExportUrl,
        effectiveChartType,
        canStackSeries,
    } = useValues(logic)
    const {
        setFilters,
        setDateRange,
        setChartType,
        toggleSeries,
        toggleAllSeries,
        setExcludeEmptySeries,
        toggleTeamBreakdown,
        resetFilters,
    } = useActions(logic)

    if (restrictionReason) {
        return <BillingNoAccess title="Usage" reason={restrictionReason} />
    }

    // Creating an export requires editor access to the export resource.
    const exportAccessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Export,
        AccessControlLevel.Editor
    )

    // The server assembles and streams the file for every breakdown. The file carries the page's
    // filters, not the series ticked in the table.

    return (
        <div className="space-y-4">
            <BillingEarlyAccessBanner />
            <div className="border rounded p-4 bg-bg-light space-y-4">
                <div className="flex gap-4 items-start flex-wrap">
                    {/* Usage Types */}
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Products</LemonLabel>
                        <LemonInputSelect
                            mode="multiple"
                            displayMode="count"
                            bulkActions="select-and-clear-all"
                            className="w-50 h-10"
                            value={filters.usage_types || []}
                            onChange={(value) => setFilters({ usage_types: value })}
                            placeholder="All products"
                            options={getUsageTypeOptions()}
                            allowCustomValues={false}
                        />
                    </div>

                    {/* Teams */}
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Projects</LemonLabel>
                        {teamIdOptionsLoading ? (
                            <LemonInput className="w-50 h-10" placeholder="Loading projects…" disabled />
                        ) : (
                            <LemonInputSelect
                                mode="multiple"
                                displayMode="count"
                                bulkActions="select-and-clear-all"
                                className="w-50 h-10"
                                value={(filters.team_ids || []).map(String)}
                                onChange={(value) =>
                                    setFilters({ team_ids: value.map(Number).filter((n) => !isNaN(n)) })
                                }
                                placeholder="All projects"
                                options={teamOptions}
                                allowCustomValues={false}
                            />
                        )}
                    </div>

                    {/* Breakdowns */}
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Break down by</LemonLabel>
                        <div className="flex gap-2 items-center min-h-10">
                            <span className="opacity-70">
                                <LemonCheckbox
                                    label="Product"
                                    checked={true}
                                    disabledReason="Breakdown by Product is required for usage volume, as summing different units (e.g., events + recordings) doesn't produce a meaningful total."
                                />
                            </span>
                            <LemonCheckbox
                                label="Project"
                                checked={(filters.breakdowns || []).includes('team')}
                                onChange={toggleTeamBreakdown}
                            />
                        </div>
                    </div>

                    {/* Top N projects. Only meaningful while breaking down by project. It is what lets an
                        organization with hundreds of projects chart the breakdown. */}
                    {(filters.breakdowns || []).includes('team') && (
                        <div className="flex flex-col gap-1">
                            <LemonLabel>Show projects</LemonLabel>
                            <div className="bg-bg-light rounded-md">
                                <LemonSelect
                                    className="h-10.5 flex items-center"
                                    size="small"
                                    value={filters.top_projects ?? null}
                                    onChange={(value: number | null) => setFilters({ top_projects: value })}
                                    options={[
                                        ...TOP_PROJECTS_OPTIONS.map((count) => ({
                                            value: count,
                                            label: `Top ${count}`,
                                        })),
                                        {
                                            value: null,
                                            label: 'All',
                                            tooltip: 'Showing every project can be too large to load as a chart.',
                                        },
                                    ]}
                                />
                            </div>
                        </div>
                    )}

                    {/* Line or stacked bar. A stack shows the total and its parts, which is what a project
                        breakdown is usually asked for, but it only means anything when every series shares a
                        unit, so the option is disabled when they do not. */}
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Chart</LemonLabel>
                        <div className="bg-bg-light rounded-md">
                            <LemonSelect
                                className="h-10.5 flex items-center"
                                size="small"
                                value={effectiveChartType}
                                onChange={(value: BillingChartType) => setChartType(value)}
                                options={[
                                    { value: 'line' as const, label: 'Line' },
                                    {
                                        value: 'bar' as const,
                                        label: 'Stacked bar',
                                        disabledReason: canStackSeries
                                            ? undefined
                                            : 'Stacking needs every series in the same unit. Pick a single product to stack by project.',
                                    },
                                ]}
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
                                onChange={(value) => setExcludeEmptySeries(value)}
                            />
                        </div>
                    </div>

                    {/* Clear Filters / Export */}
                    <div className="flex flex-col gap-1">
                        <LemonLabel>&nbsp;</LemonLabel>
                        <div className="flex items-center gap-2">
                            <LemonButton type="secondary" size="medium" onClick={resetFilters}>
                                Clear filters
                            </LemonButton>
                            {/* Not gated on the chart having loaded: the file is built on the server from the same
                                filters, and it is what the guidance offers when the chart times out or is too large.
                                Two files, because the chart's cap is not a filter: the first is the data for the period
                                under the page's filters, "the chart's series" is what is drawn. */}
                            <LemonMenu
                                items={[
                                    {
                                        label:
                                            filters.team_ids?.length &&
                                            !selectionCoversEveryProject(filters.team_ids, teamOptions)
                                                ? `Selected projects in this period (${filters.team_ids.length})`
                                                : 'All projects in this period',
                                        onClick: () => window.location.assign(usageExportUrl),
                                    },
                                    filters.breakdowns?.includes('team') && filters.top_projects
                                        ? {
                                              label: `The chart's series (top ${filters.top_projects} and the rest folded)`,
                                              onClick: () => window.location.assign(usageChartExportUrl),
                                          }
                                        : null,
                                ]}
                                placement="bottom-end"
                            >
                                <LemonButton
                                    type="secondary"
                                    size="medium"
                                    sideIcon={<IconChevronDown />}
                                    disabledReason={exportAccessControlDisabledReason ?? undefined}
                                >
                                    Export CSV
                                </LemonButton>
                            </LemonMenu>
                        </div>
                    </div>
                </div>

                {billingUsageError && (
                    <LemonBanner type="warning">{billingErrorGuidance(billingUsageError)}</LemonBanner>
                )}

                {showSeries && (
                    <BillingChart
                        series={series}
                        dates={dates}
                        isLoading={billingUsageResponseLoading}
                        hiddenSeries={finalHiddenSeries}
                        showLegend={false}
                        interval={filters.interval}
                        billingPeriodMarkers={billingPeriodMarkers}
                        chartType={effectiveChartType}
                    />
                )}
                {showEmptyState && (
                    <BillingEmptyState
                        heading="We couldn't find any usage data for your current query."
                        detail="Try adjusting the filters. If you think something is wrong, contact us!"
                    />
                )}
            </div>

            {showSeries ? (
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
                        isLoading={billingUsageResponseLoading}
                        hiddenSeries={finalHiddenSeries}
                        toggleSeries={toggleSeries}
                        toggleAllSeries={toggleAllSeries}
                    />
                </div>
            ) : null}
        </div>
    )
}
