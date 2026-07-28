import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCalendar, IconInfo } from '@posthog/icons'
import {
    Button,
    Label,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Switch,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import {
    DateFilterExclusionsControl,
    dateFilterExclusionParts,
    type DateFilterExclusions,
} from 'lib/components/DateFilter/DateFilterExclusionsControl'
import { selectionKeyOf, type DateRangeSelection } from 'lib/components/DateFilter/DateRangePresetsPanel'
import { dateRangeForSelection, selectionForDateRange } from 'lib/components/DateFilter/dateRangeSelection'
import { QuillDateFilter } from 'lib/components/DateFilter/QuillDateFilter'
import { dateFilterToText, dateMapping } from 'lib/utils/dateFilters'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { computeDaysOfWeekUpdate, getExcludedDaysOfWeek, type IsoDayOfWeek } from './daysOfWeekFilterUtils'

// Chip labels double as dateMapping keys; filter at module load so a renamed chip can never
// silently produce the wrong range.
const NAMED_CHIPS = ['Today', 'Yesterday', 'This week', 'This month', 'This year', 'All time'].filter((name) =>
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
    const { dateRange, trendsFilter, isTrends, isRetention, querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange, updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { reportInsightDatePickerOpened } = useActions(eventUsageLogic)
    const { weekStartDay } = useValues(teamLogic)
    const [open, setOpen] = useState(false)

    const storeSelection = selectionForDateRange(dateRange?.date_from ?? '-7d', dateRange?.date_to)
    // The store updates only after the logic's 300ms debounce — reflect picks immediately
    // so rapid stepper presses accumulate instead of re-deriving from a stale value.
    const [pendingSelection, setPendingSelection] = useState<DateRangeSelection | null>(null)
    const storeSelectionKey = selectionKeyOf(storeSelection)
    useEffect(() => {
        setPendingSelection(null)
    }, [storeSelectionKey])
    const selection = pendingSelection ?? storeSelection
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

    // Hiding the exclusions control (smoothing turned on, or the insight type changed away from
    // trends) must also clear any daysOfWeek already on the query — otherwise it lingers with no
    // UI left to remove it, and the backend rejects daysOfWeek alongside smoothing.
    useEffect(() => {
        if (!showExcludedDays && dateRange?.daysOfWeek?.length) {
            updateQuerySource(computeDaysOfWeekUpdate([], dateRange))
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [showExcludedDays])
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
        <Popover
            open={open}
            onOpenChange={(next) => {
                if (next && !open) {
                    reportInsightDatePickerOpened(querySource?.kind)
                }
                setOpen(next)
            }}
        >
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
                <QuillDateFilter
                    selection={selection}
                    onSelectionChange={(next) => {
                        setPendingSelection(next)
                        // Rolling changes ride the stepper click-by-click, so let them debounce
                        updateDateRange(dateRangeForSelection(next), next.kind !== 'rolling')
                        if (next.kind !== 'rolling') {
                            setOpen(false)
                        }
                    }}
                    onApplyCustom={(next) => {
                        updateDateRange(dateRangeForSelection(next), true)
                        setOpen(false)
                    }}
                    namedChips={NAMED_CHIPS}
                    weekStartsOn={weekStartDay === 1 ? 1 : 0}
                    portalProps={LEMON_SKIN_PROPS}
                    presetsFooter={
                        <>
                            <div className="flex h-8 items-center justify-between gap-2 px-2">
                                <Label htmlFor="date-filter-exact-time" className="flex items-center gap-1">
                                    Exact time range
                                    <Tooltip>
                                        <TooltipTrigger render={<span className="inline-flex" />}>
                                            <IconInfo className="h-4 w-4 text-muted-foreground" />
                                        </TooltipTrigger>
                                        <TooltipContent className="max-w-64 flex-col items-start whitespace-normal">
                                            <span>
                                                When enabled: uses the current time for period boundaries instead of
                                                full days.
                                            </span>
                                            <span>
                                                When disabled: dates are rounded to full day periods (start and end of
                                                day).
                                            </span>
                                        </TooltipContent>
                                    </Tooltip>
                                </Label>
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
