import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import { Button, DateTimePicker, Label, Popover, PopoverContent, PopoverTrigger, Switch } from '@posthog/quill'

import {
    DateFilterExclusionsControl,
    dateFilterExclusionParts,
    type DateFilterExclusions,
} from 'lib/components/DateFilter/DateFilterExclusionsControl'
import { dateRangeForSelection, selectionForDateRange } from 'lib/components/DateFilter/dateRangeSelection'
import { dateFilterToText, dateMapping } from 'lib/utils/dateFilters'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { computeDaysOfWeekUpdate, getExcludedDaysOfWeek, type IsoDayOfWeek } from './daysOfWeekFilterUtils'

// Chip labels double as dateMapping keys; filter at module load so a renamed chip can never
// silently produce the wrong range.
const NAMED_CHIPS = ['Today', 'Yesterday', 'This week', 'This month', 'Year to date', 'All time'].filter((name) =>
    dateMapping.some(({ key }) => key === name)
)

function shortExclusionsLabel(parts: string[]): string {
    return parts.length > 1 ? `excl. ${parts[0]} +${parts.length - 1}` : `excl. ${parts[0]}`
}

const LEMON_SKIN_PROPS = { 'data-lemon-skin': 'true' }

type InsightQuillDateFilterProps = {
    disabled: boolean
}

export function InsightQuillDateFilter({ disabled }: InsightQuillDateFilterProps): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { dateRange, trendsFilter, isTrends, isRetention } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange, updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { weekStartDay } = useValues(teamLogic)
    const [open, setOpen] = useState(false)

    const selection = selectionForDateRange(dateRange?.date_from ?? '-7d', dateRange?.date_to)
    const triggerLabel =
        dateFilterToText(dateRange?.date_from ?? '-7d', dateRange?.date_to, 'Last 7 days', dateMapping, false) ??
        'Last 7 days'

    // The picker speaks excluded days; the query schema stores included days. The legacy
    // display-only trendsFilter.hideWeekends is deliberately NOT folded in — different semantics.
    const excludedDays = getExcludedDaysOfWeek(dateRange)
    // The backend rejects daysOfWeek together with smoothing, so don't offer it
    const smoothingActive = isTrends && (trendsFilter?.smoothingIntervals ?? 1) > 1
    const showExcludedDays = isTrends && !smoothingActive
    const showIncompletePeriod = !isRetention
    const exclusions: DateFilterExclusions = {
        days: isTrends ? excludedDays.map(String) : [],
        incomplete: !isRetention && !!dateRange?.excludeIncompletePeriods,
    }
    const handleExclusionsChange = (next: DateFilterExclusions): void => {
        if (isTrends && next.days.join(',') !== exclusions.days.join(',')) {
            updateQuerySource(computeDaysOfWeekUpdate(next.days.map(Number) as IsoDayOfWeek[], dateRange))
        }
        if (!isRetention && next.incomplete !== exclusions.incomplete) {
            updateDateRange({ excludeIncompletePeriods: next.incomplete ? true : null }, true)
        }
    }

    const exclusionParts = dateFilterExclusionParts(exclusions)

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        data-quill
                        data-lemon-skin
                        disabled={disabled || !!editingDisabledReason}
                        title={editingDisabledReason ?? undefined}
                        data-attr="insight-quill-date-filter"
                    />
                }
            >
                <IconCalendar />
                {triggerLabel}
                {exclusionParts.length > 0 && (
                    <span className="text-muted-foreground font-normal">· {shortExclusionsLabel(exclusionParts)}</span>
                )}
            </PopoverTrigger>
            <PopoverContent
                align="start"
                collisionAvoidance={{ side: 'flip', align: 'shift', fallbackAxisSide: 'none' }}
                className="w-auto overflow-hidden border-none p-0 shadow-none ring-0"
                {...LEMON_SKIN_PROPS}
            >
                <DateTimePicker
                    selection={selection}
                    onSelectionChange={(next) => {
                        // Rolling changes ride the stepper keystroke-by-keystroke, so let them debounce
                        updateDateRange(dateRangeForSelection(next), next.kind !== 'rolling')
                        if (next.kind !== 'rolling') {
                            setOpen(false)
                        }
                    }}
                    onApply={({ start, end, includesTime }) => {
                        updateDateRange(dateRangeForSelection({ kind: 'custom', start, end, includesTime }), true)
                        setOpen(false)
                    }}
                    namedChips={NAMED_CHIPS}
                    showHeader={false}
                    showTime={false}
                    showTimeToggle
                    weekStartsOn={weekStartDay === 1 ? 1 : 0}
                    portalProps={LEMON_SKIN_PROPS}
                    presetsFooter={
                        <>
                            <div className="flex h-8 items-center justify-between gap-2 px-2">
                                <Label htmlFor="date-filter-exact-time">Exact time range</Label>
                                <Switch
                                    id="date-filter-exact-time"
                                    size="sm"
                                    checked={dateRange?.explicitDate ?? false}
                                    onCheckedChange={(checked) => updateDateRange({ explicitDate: checked }, true)}
                                />
                            </div>
                            {(showExcludedDays || showIncompletePeriod) && (
                                <DateFilterExclusionsControl
                                    exclusions={exclusions}
                                    onChange={handleExclusionsChange}
                                    showDays={showExcludedDays}
                                    showIncomplete={showIncompletePeriod}
                                    panelProps={LEMON_SKIN_PROPS}
                                />
                            )}
                        </>
                    }
                />
            </PopoverContent>
        </Popover>
    )
}
