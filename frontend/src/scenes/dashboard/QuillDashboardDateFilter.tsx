import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import {
    Button,
    Label,
    Popover,
    PopoverContent,
    PopoverTrigger,
    SelectTriggerIcon,
    Switch,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import type { DateRangeSelection } from 'lib/components/DateFilter/DateRangePresetsPanel'
import { dateRangeForSelection, selectionForDateRange } from 'lib/components/DateFilter/dateRangeSelection'
import { QuillDateFilter } from 'lib/components/DateFilter/QuillDateFilter'
import { NO_OVERRIDE_RANGE_PLACEHOLDER } from 'lib/components/DateFilter/types'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { dateFilterToText } from 'lib/utils/dateFilters'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

// No chip matches this name, so the picker shows no preset as selected while each insight keeps its own range.
const NO_OVERRIDE_SELECTION: DateRangeSelection = { kind: 'fixed', name: NO_OVERRIDE_RANGE_PLACEHOLDER }

/** The dashboard date range override: a quill trigger over the quill date picker. */
export function QuillDashboardDateFilter(): JSX.Element {
    const { dashboardEditing, effectiveEditBarFilters } = useValues(dashboardLogic)
    const { setDates, setDashboardEditing } = useActions(dashboardLogic)
    const { weekStartDay } = useValues(teamLogic)
    const [open, setOpen] = useState(false)

    const { date_from: dateFrom, date_to: dateTo, explicitDate } = effectiveEditBarFilters
    const hasOverride = !!dateFrom || !!dateTo
    const selection = dateFrom ? selectionForDateRange(dateFrom, dateTo) : NO_OVERRIDE_SELECTION
    const label = hasOverride
        ? (dateFilterToText(dateFrom, dateTo, NO_OVERRIDE_RANGE_PLACEHOLDER) ?? NO_OVERRIDE_RANGE_PLACEHOLDER)
        : NO_OVERRIDE_RANGE_PLACEHOLDER

    const applyDates = (from: string | null, to: string | null | undefined, explicit: boolean | undefined): void => {
        if (!dashboardEditing?.filters) {
            setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
        }
        setDates(from, to, explicit)
    }
    const applySelection = (nextSelection: DateRangeSelection, explicit: boolean | undefined): void => {
        const range = dateRangeForSelection(nextSelection)
        applyDates(range.date_from ?? null, range.date_to, explicit)
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <Shortcut
                name="DashboardDateFilter"
                keybind={[keyBinds.dateFilter]}
                intent="Date filter"
                interaction="click"
                scope={Scene.Dashboard}
            >
                <PopoverTrigger render={<Button variant="outline" data-attr="date-filter" />}>
                    <IconCalendar />
                    <span className="truncate">{label}</span>
                    <SelectTriggerIcon />
                </PopoverTrigger>
            </Shortcut>
            <PopoverContent
                align="start"
                collisionAvoidance={{ side: 'flip', align: 'shift', fallbackAxisSide: 'none' }}
                className="w-auto overflow-hidden border-none p-0 shadow-none ring-0"
            >
                <QuillDateFilter
                    selection={selection}
                    onSelectionChange={(nextSelection) => {
                        applySelection(nextSelection, explicitDate)
                        // Rolling steppers keep the panel open so the count can be nudged.
                        if (nextSelection.kind !== 'rolling') {
                            setOpen(false)
                        }
                    }}
                    onApplyCustom={(nextSelection) => {
                        // A range picked with times is exact, the same as the legacy filter's time toggle.
                        applySelection(nextSelection, !!nextSelection.includesTime || explicitDate)
                        setOpen(false)
                    }}
                    weekStartsOn={weekStartDay === 1 ? 1 : 0}
                    presetsFooter={
                        <>
                            <div className="flex h-8 items-center justify-between gap-2 px-2">
                                <Tooltip>
                                    <TooltipTrigger render={<Label htmlFor="dashboard-date-filter-exact-time" />}>
                                        Exact time range
                                    </TooltipTrigger>
                                    <TooltipContent>
                                        <div className="flex flex-col gap-1">
                                            <span>On: period boundaries use the current time.</span>
                                            <span>Off: dates round to full days.</span>
                                        </div>
                                    </TooltipContent>
                                </Tooltip>
                                <Switch
                                    id="dashboard-date-filter-exact-time"
                                    size="sm"
                                    checked={!!explicitDate}
                                    onCheckedChange={(checked) => applyDates(dateFrom ?? null, dateTo, checked)}
                                    disabledReason={hasOverride ? undefined : 'Pick a date range first'}
                                />
                            </div>
                            {hasOverride && (
                                <Button
                                    left
                                    className="w-full"
                                    onClick={() => {
                                        applyDates(null, null, false)
                                        setOpen(false)
                                    }}
                                    data-attr="dashboard-date-filter-clear"
                                >
                                    Use each insight's date range
                                </Button>
                            )}
                        </>
                    }
                />
            </PopoverContent>
        </Popover>
    )
}
