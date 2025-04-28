import './BillingUsage.scss' // Keep existing styles for now

import { LemonCheckbox } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { useEffect, useMemo, useState } from 'react' // Added useEffect, useMemo
import { organizationLogic } from 'scenes/organizationLogic' // Added organizationLogic

import { BillingDataTable } from './BillingDataTable' // Import shared table component
import { BillingLineGraph } from './BillingLineGraph' // Import shared component
import { billingSpendLogic } from './billingSpendLogic' // Use spend logic

// Copied from BillingUsage
const USAGE_TYPES = [
    { label: 'Events', value: 'event_count_in_period' },
    { label: 'Recordings', value: 'recording_count_in_period' },
    { label: 'Mobile Recordings', value: 'mobile_recording_count_in_period' },
    { label: 'Feature Flags', value: 'billable_feature_flag_requests_count_in_period' },
    { label: 'Exceptions', value: 'exceptions_captured_in_period' },
    { label: 'Rows Synced', value: 'rows_synced_in_period' },
    { label: 'Persons', value: 'enhanced_persons_event_count_in_period' },
    { label: 'Survey Responses', value: 'survey_responses_count_in_period' },
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
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic) // Added
    const [userHiddenSeries, setUserHiddenSeries] = useState<number[]>([]) // Renamed
    const [excludeEmptySeries, setExcludeEmptySeries] = useState<boolean>(false) // Added

    // --- Constants for all keys (Copied from BillingUsage) ---
    const allUsageTypeKeys = USAGE_TYPES.map((opt) => opt.value)
    const allTeamIDs = currentOrganization?.teams?.map((team) => team.id) || []
    // --- End constants ---

    // --- Initialize filters to "all selected" once data is loaded (Copied from BillingUsage) ---
    useEffect(() => {
        // We only want to run this once when the component mounts and data is ready
        if (currentOrganization && !currentOrganizationLoading) {
            const updates: Partial<typeof filters> = {}
            if (!filters.usage_types || filters.usage_types.length === 0) {
                updates.usage_types = allUsageTypeKeys
            }
            if (!filters.team_ids || filters.team_ids.length === 0) {
                updates.team_ids = allTeamIDs
            }
            if (Object.keys(updates).length > 0) {
                setFilters(updates)
            }
        }
    }, [currentOrganization, currentOrganizationLoading]) // Watch organization load state
    // --- End filter initialization ---

    // Updated breakdown logic to allow toggling type and team independently
    const handleBreakdownChange = (dimension: 'type' | 'team'): void => {
        const currentBreakdowns = filters.breakdowns || []
        let newBreakdowns: ('type' | 'team')[] = [...currentBreakdowns] // Start with current

        if (newBreakdowns.includes(dimension)) {
            // If it exists, remove it
            newBreakdowns = newBreakdowns.filter((d) => d !== dimension)
        } else {
            // If it doesn't exist, add it
            newBreakdowns.push(dimension)
        }

        setFilters({ breakdowns: newBreakdowns })
    }

    // Function to toggle a series visibility by ID (Renamed hiddenSeries -> userHiddenSeries)
    const toggleSeries = (id: number): void => {
        setUserHiddenSeries((prevHidden) =>
            prevHidden.includes(id) ? prevHidden.filter((i) => i !== id) : [...prevHidden, id]
        )
    }

    // Function to toggle all series visibility (Renamed hiddenSeries -> userHiddenSeries, added excludeEmptySeries logic)
    const toggleAllSeries = (): void => {
        const potentiallyVisibleSeries = excludeEmptySeries
            ? series.filter((s) => s.data.reduce((a, b) => a + b, 0) > 0)
            : series
        const potentiallyVisibleIDs = potentiallyVisibleSeries.map((s) => s.id)

        const allPotentiallyVisibleAreHidden = potentiallyVisibleIDs.every((id) => userHiddenSeries.includes(id))

        if (allPotentiallyVisibleAreHidden && potentiallyVisibleIDs.length > 0) {
            setUserHiddenSeries([])
        } else if (potentiallyVisibleIDs.length > 0) {
            setUserHiddenSeries(potentiallyVisibleIDs)
        }
    }

    // --- Calculate IDs of empty series (Copied from BillingUsage) ---
    const emptySeriesIDs = useMemo(() => {
        return series.filter((s) => s.data.reduce((a, b) => a + b, 0) === 0).map((s) => s.id)
    }, [series])
    // --- End calculation ---

    // --- Compute final list of hidden series based on user toggles and excludeEmpty filter (Copied from BillingUsage) ---
    const finalHiddenSeries = useMemo(() => {
        return excludeEmptySeries
            ? Array.from(new Set([...userHiddenSeries, ...emptySeriesIDs])) // Combine and deduplicate
            : userHiddenSeries // Only use manually hidden ones
    }, [excludeEmptySeries, userHiddenSeries, emptySeriesIDs])
    // ---

    return (
        <div className="space-y-4">
            {/* --- Replicated Filter Layout from BillingUsage --- */}
            <div className="flex gap-4 items-start flex-wrap">
                {/* Usage Types Filter */}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Usage Types</LemonLabel>
                    <LemonInputSelect
                        mode="multiple"
                        displayMode="count"
                        showSelectAll={true}
                        showClearAll={true}
                        autoWidth={false}
                        className="h-10"
                        value={filters.usage_types || []}
                        onChange={(value) => setFilters({ usage_types: value })}
                        placeholder="All usage types"
                        options={USAGE_TYPES.map((opt) => ({ key: opt.value, label: opt.label }))}
                        allowCustomValues={false}
                    />
                </div>

                {/* Teams Filter */}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Teams</LemonLabel>
                    <LemonInputSelect
                        mode="multiple"
                        displayMode="count"
                        showSelectAll={true}
                        showClearAll={true}
                        autoWidth={false}
                        className="h-10"
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

                {/* Breakdown Options - Now both are toggleable */}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Break down by</LemonLabel>
                    <div className="flex gap-2 items-center min-h-10">
                        <LemonCheckbox
                            label="Type"
                            checked={(filters.breakdowns || []).includes('type')}
                            onChange={() => handleBreakdownChange('type')} // Allow toggle
                        />
                        <LemonCheckbox
                            label="Team"
                            checked={(filters.breakdowns || []).includes('team')}
                            onChange={() => handleBreakdownChange('team')} // Allow toggle
                        />
                    </div>
                </div>

                {/* Date Filter */}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Date range</LemonLabel>
                    <div className="bg-bg-light rounded-md">
                        <DateFilter
                            className="h-8 flex items-center"
                            dateFrom={dateFrom}
                            dateTo={dateTo}
                            onChange={(fromDate, toDate) => setDateRange(fromDate || null, toDate || null)}
                        />
                    </div>
                </div>

                {/* Exclude Empty Series Checkbox */}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Options</LemonLabel>
                    <div className="flex items-center min-h-10">
                        <LemonCheckbox
                            label="Hide results with no spend" // Updated label
                            checked={excludeEmptySeries}
                            onChange={setExcludeEmptySeries}
                        />
                    </div>
                </div>
            </div>
            {/* --- End Updated Filter Layout --- */}

            {/* Always render graph/table area, logic inside handles loading/empty states */}
            <>
                <div className="border rounded p-4 bg-white">
                    {/* Use shared BillingLineGraph component with currency formatter */}
                    <BillingLineGraph
                        series={series}
                        dates={dates}
                        isLoading={billingSpendResponseLoading} // Use spend loading state
                        hiddenSeries={finalHiddenSeries} // Use final computed hidden series
                        valueFormatter={currencyFormatter} // Pass the currency formatter
                        showLegend={false} // Disable legend
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
                            hiddenSeries={finalHiddenSeries} // Use final computed hidden series
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
