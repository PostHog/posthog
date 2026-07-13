import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    Button as QuillButton,
    composerExclusionParts,
    DateRangeComposer,
    Popover as QuillPopover,
    PopoverContent as QuillPopoverContent,
    PopoverTrigger as QuillPopoverTrigger,
    type DateRangeComposerExclusions,
    type DateRangeComposerSelection,
    type RelativeRangeUnit,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { dateFilterToText, dateMapping, dateStringToDayJs } from 'lib/utils/dateFilters'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { DateRange } from '~/queries/schema/schema-general'

import { computeDaysOfWeekUpdate, getExcludedDaysOfWeek, type IsoDayOfWeek } from './daysOfWeekFilterUtils'

// Only the units the composer's rolling input speaks; everything else (quarters, minutes,
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
    minutes: 'h', // not offered in the composer; mapped defensively
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

/** PostHog relative-date strings → a composer selection. Named periods resolve through
 *  `dateMapping`, so the composer's chip names and the query vocabulary can't drift. Anything
 *  the composer can't express (quarters, minute ranges, Start/End anchors, relative pairs)
 *  resolves through the canonical parser to a concrete custom range — never a fabricated preset. */
export function selectionForDateRange(dateFrom: string, dateTo: string | null | undefined): DateRangeComposerSelection {
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

export function dateRangeForSelection(selection: DateRangeComposerSelection): Partial<DateRange> {
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

    // The composer speaks excluded days; the query schema stores included days. The legacy
    // display-only trendsFilter.hideWeekends is deliberately NOT folded in — different semantics.
    const excludedDays = getExcludedDaysOfWeek(dateRange)
    // The backend rejects daysOfWeek together with smoothing, so don't offer it
    const smoothingActive = isTrends && (trendsFilter?.smoothingIntervals ?? 1) > 1
    const exclusions: DateRangeComposerExclusions = {
        days: isTrends ? excludedDays.map(String) : [],
        incomplete: !isRetention && !!dateRange?.excludeIncompletePeriods,
    }
    const handleExclusionsChange = (next: DateRangeComposerExclusions): void => {
        if (isTrends && next.days.join(',') !== exclusions.days.join(',')) {
            updateQuerySource(computeDaysOfWeekUpdate(next.days.map(Number) as IsoDayOfWeek[], dateRange))
        }
        if (!isRetention && next.incomplete !== exclusions.incomplete) {
            updateDateRange({ excludeIncompletePeriods: next.incomplete ? true : null }, true)
        }
    }

    const exclusionParts = composerExclusionParts(exclusions)

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
                {triggerLabel}
                {exclusionParts.length > 0 && (
                    <span className="text-muted-foreground font-normal">· {shortExclusionsLabel(exclusionParts)}</span>
                )}
            </QuillPopoverTrigger>
            <QuillPopoverContent
                align="start"
                collisionAvoidance={{ side: 'flip', align: 'none', fallbackAxisSide: 'none' }}
                className="w-auto overflow-hidden border-none p-0 shadow-none ring-0"
                {...LEMON_SKIN_PROPS}
            >
                <DateRangeComposer
                    selection={selection}
                    onSelect={(next) => {
                        // Rolling changes ride the stepper keystroke-by-keystroke, so let them debounce
                        updateDateRange(dateRangeForSelection(next), next.kind !== 'rolling')
                        if (next.kind !== 'rolling') {
                            setOpen(false)
                        }
                    }}
                    exclusions={exclusions}
                    onExclusionsChange={handleExclusionsChange}
                    namedChips={NAMED_CHIPS}
                    showExcludedDays={isTrends && !smoothingActive}
                    showIncompletePeriod={!isRetention}
                    weekStartsOn={weekStartDay === 1 ? 1 : 0}
                    exactTime={dateRange?.explicitDate ?? false}
                    onExactTimeChange={(checked) => updateDateRange({ explicitDate: checked }, true)}
                    portalProps={LEMON_SKIN_PROPS}
                />
            </QuillPopoverContent>
        </QuillPopover>
    )
}
