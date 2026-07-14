import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import {
    Button as QuillButton,
    DateTimePicker,
    Label as QuillLabel,
    Popover as QuillPopover,
    PopoverContent as QuillPopoverContent,
    PopoverTrigger as QuillPopoverTrigger,
    Switch as QuillSwitch,
    type DateRangeSelection,
    type RelativeRangeUnit,
} from '@posthog/quill'

import {
    DateFilterExclusionsControl,
    dateFilterExclusionParts,
    type DateFilterExclusions,
} from 'lib/components/DateFilter/DateFilterExclusionsControl'
import { dayjs } from 'lib/dayjs'
import { dateFilterToText, dateMapping, dateStringToDayJs } from 'lib/utils/dateFilters'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { DateRange } from '~/queries/schema/schema-general'

import { computeDaysOfWeekUpdate, getExcludedDaysOfWeek, type IsoDayOfWeek } from './daysOfWeekFilterUtils'

// Only the units the picker's rolling input speaks; everything else (quarters, minutes,
// seconds, Start/End anchors) resolves to a concrete custom range below.
const ROLLING_DATE_FROM = /^-(\d+)([hdwmy])$/
const UNIT_BY_LETTER: Record<string, RelativeRangeUnit> = {
    h: 'hours',
    d: 'days',
    w: 'weeks',
    m: 'months',
    y: 'years',
}
const LETTER_BY_UNIT: Record<RelativeRangeUnit, string> = {
    minutes: 'h', // not offered in the picker; mapped defensively
    hours: 'h',
    days: 'd',
    weeks: 'w',
    months: 'm',
    years: 'y',
}

// Chip labels double as dateMapping keys; filter at module load so a renamed chip can never
// silently produce the wrong range.
const NAMED_CHIPS = ['Today', 'Yesterday', 'This week', 'This month', 'Year to date', 'All time'].filter((name) =>
    dateMapping.some(({ key }) => key === name)
)

/** PostHog relative-date strings → a picker selection. Named periods resolve through
 *  `dateMapping`, so the picker's chip names and the query vocabulary can't drift. Anything
 *  the picker can't express (quarters, minute ranges, Start/End anchors, relative pairs)
 *  resolves through the canonical parser to a concrete custom range — never a fabricated preset. */
export function selectionForDateRange(dateFrom: string, dateTo: string | null | undefined): DateRangeSelection {
    const rolling = !dateTo && dateFrom.match(ROLLING_DATE_FROM)
    if (rolling) {
        return { kind: 'rolling', count: parseInt(rolling[1], 10), unit: UNIT_BY_LETTER[rolling[2]] }
    }
    const named = dateMapping.find(({ values }) => values[0] === dateFrom && (values[1] ?? null) === (dateTo ?? null))
    if (named) {
        return { kind: 'fixed', name: named.key }
    }
    const start = dateStringToDayJs(dateFrom) ?? (dayjs(dateFrom).isValid() ? dayjs(dateFrom) : null)
    const end = dateTo ? (dateStringToDayJs(dateTo) ?? (dayjs(dateTo).isValid() ? dayjs(dateTo) : null)) : dayjs()
    if (start) {
        return { kind: 'custom', start: start.toDate(), end: (end ?? dayjs()).toDate() }
    }
    return { kind: 'custom', start: dayjs().subtract(7, 'day').toDate(), end: dayjs().toDate() }
}

function formatCustomDate(date: Date, includesTime: boolean): string {
    return dayjs(date).format(includesTime ? 'YYYY-MM-DDTHH:mm:ss' : 'YYYY-MM-DD')
}

export function dateRangeForSelection(selection: DateRangeSelection): Partial<DateRange> {
    if (selection.kind === 'rolling') {
        return { date_from: `-${selection.count}${LETTER_BY_UNIT[selection.unit]}`, date_to: null }
    }
    if (selection.kind === 'fixed') {
        const named = dateMapping.find(({ key }) => key === selection.name)
        return { date_from: named?.values[0] ?? null, date_to: named?.values[1] ?? null }
    }
    const includesTime = !!selection.includesTime
    return {
        date_from: formatCustomDate(selection.start, includesTime),
        date_to: formatCustomDate(selection.end, includesTime),
        // Without explicitDate the backend floors/ceils to whole days, discarding picked times
        explicitDate: includesTime,
    }
}

function shortExclusionsLabel(parts: string[]): string {
    return parts.length > 1 ? `excl. ${parts[0]} +${parts.length - 1}` : `excl. ${parts[0]}`
}

const LEMON_SKIN_PROPS = { 'data-lemon-skin': 'true' }

type InsightDateFilterComposerProps = {
    disabled: boolean
}

export function InsightDateFilterComposer({ disabled }: InsightDateFilterComposerProps): JSX.Element {
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
        <QuillPopover open={open} onOpenChange={setOpen}>
            <QuillPopoverTrigger
                render={
                    <QuillButton
                        variant="outline"
                        data-quill
                        data-lemon-skin
                        disabled={disabled || !!editingDisabledReason}
                        title={editingDisabledReason ?? undefined}
                        data-attr="insight-date-filter-composer"
                    />
                }
            >
                <IconCalendar />
                {triggerLabel}
                {exclusionParts.length > 0 && (
                    <span className="text-muted-foreground font-normal">· {shortExclusionsLabel(exclusionParts)}</span>
                )}
            </QuillPopoverTrigger>
            <QuillPopoverContent
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
                                <QuillLabel htmlFor="composer-exact-time">Exact time range</QuillLabel>
                                <QuillSwitch
                                    id="composer-exact-time"
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
            </QuillPopoverContent>
        </QuillPopover>
    )
}
