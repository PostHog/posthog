import './BillingUsage.scss'

import { LemonCheckbox, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { useEffect, useMemo, useState } from 'react'
import { organizationLogic } from 'scenes/organizationLogic'

import { BillingDataTable } from './BillingDataTable'
import { BillingLineGraph } from './BillingLineGraph'
import { billingUsageLogic } from './billingUsageLogic'

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

export function BillingUsage(): JSX.Element {
    const logic = billingUsageLogic({ dashboardItemId: 'usage' })
    const { series, dates, filters, dateFrom, dateTo, billingUsageResponseLoading } = useValues(logic)
    const { setFilters, setDateRange } = useActions(logic)
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const [userHiddenSeries, setUserHiddenSeries] = useState<number[]>([])
    const [excludeEmptySeries, setExcludeEmptySeries] = useState<boolean>(false)

    // --- Constants for all keys ---
    const allUsageTypeKeys = USAGE_TYPES.map((opt) => opt.value)
    const allTeamIDs = currentOrganization?.teams?.map((team) => team.id) || []
    // --- End constants ---

    // --- Initialize filters to "all selected" once data is loaded ---
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

    const handleBreakdownChange = (): void => {
        // Toggle only the 'team' dimension. 'type' is always implicitly active (UI disabled).
        const currentBreakdowns = filters.breakdowns || []
        const newBreakdowns: ('type' | 'team')[] = []
        // Preserve 'type' if it exists (it might not if default was changed, though UI implies it)
        if (currentBreakdowns.includes('type')) {
            newBreakdowns.push('type')
        }
        // Toggle 'team'
        if (!currentBreakdowns.includes('team')) {
            newBreakdowns.push('team') // Add team if it wasn't there
        } // If 'team' was there, it's implicitly removed by not adding it here

        // API validation handles the case where team breakdown is active with no usage_types selected
        setFilters({ breakdowns: newBreakdowns })
    }

    // Function to toggle a series visibility by ID
    const toggleSeries = (id: number): void => {
        setUserHiddenSeries((prevHidden) =>
            prevHidden.includes(id) ? prevHidden.filter((i) => i !== id) : [...prevHidden, id]
        )
    }

    // Function to toggle all series visibility
    const toggleAllSeries = (): void => {
        // Toggle all affects the userHiddenSeries state.
        // Consider only series that *could* be visible (i.e., non-empty if excludeEmptySeries is true)
        const potentiallyVisibleSeries = excludeEmptySeries
            ? series.filter((s) => s.data.reduce((a, b) => a + b, 0) > 0)
            : series
        const potentiallyVisibleIDs = potentiallyVisibleSeries.map((s) => s.id)

        // Check if all potentially visible series are currently manually hidden
        const allPotentiallyVisibleAreHidden = potentiallyVisibleIDs.every((id) => userHiddenSeries.includes(id))

        if (allPotentiallyVisibleAreHidden && potentiallyVisibleIDs.length > 0) {
            // If all are hidden, show them by clearing userHiddenSeries
            setUserHiddenSeries([])
        } else if (potentiallyVisibleIDs.length > 0) {
            // Hide all series
            // Otherwise, hide all potentially visible ones by setting userHiddenSeries to their IDs
            setUserHiddenSeries(potentiallyVisibleIDs)
        }
    }

    // --- Calculate IDs of empty series ---
    const emptySeriesIDs = useMemo(() => {
        return series.filter((s) => s.data.reduce((a, b) => a + b, 0) === 0).map((s) => s.id)
    }, [series])
    // --- End calculation ---

    // --- Compute final list of hidden series based on user toggles and excludeEmpty filter ---
    const finalHiddenSeries = useMemo(() => {
        return excludeEmptySeries
            ? Array.from(new Set([...userHiddenSeries, ...emptySeriesIDs])) // Combine and deduplicate
            : userHiddenSeries // Only use manually hidden ones
    }, [excludeEmptySeries, userHiddenSeries, emptySeriesIDs])
    // ---

    return (
        <div className="space-y-4">
            <div className="flex gap-4 items-start flex-wrap">
                {/* Usage Types Filter + Buttons */}
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

                {/* Teams Filter + Buttons */}
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

                {/* Breakdown Options */}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Break down by</LemonLabel>
                    <div className="flex gap-2 items-center min-h-10">
                        <Tooltip title="Breakdown by Type is required for usage volume, as summing different units (e.g., events + recordings) doesn't produce a meaningful total.">
                            <span className="opacity-70">
                                <LemonCheckbox label="Type" checked={true} disabled={true} />
                            </span>
                        </Tooltip>
                        <LemonCheckbox
                            label="Team"
                            checked={(filters.breakdowns || []).includes('team')}
                            onChange={() => handleBreakdownChange('team')}
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
                            label="Hide results with no usage"
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
                    <BillingLineGraph
                        series={series}
                        dates={dates}
                        isLoading={billingUsageResponseLoading}
                        hiddenSeries={finalHiddenSeries}
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
                            hiddenSeries={finalHiddenSeries}
                            toggleSeries={toggleSeries}
                            toggleAllSeries={toggleAllSeries}
                        />
                    </div>
                )}
            </>
        </div>
    )
}
