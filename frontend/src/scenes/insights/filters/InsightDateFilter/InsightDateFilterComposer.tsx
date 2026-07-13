import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    Button as QuillButton,
    composerExclusionsSummary,
    composerSelectionLabel,
    DateRangeComposer,
    Popover as QuillPopover,
    PopoverContent as QuillPopoverContent,
    PopoverTrigger as QuillPopoverTrigger,
    type DateRangeComposerExclusions,
    type DateRangeComposerProps,
    type DateRangeComposerSelection,
    type RelativeRangeUnit,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { dateMapping } from 'lib/utils/dateFilters'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DateRange } from '~/queries/schema/schema-general'

import {
    ALL_DAY_NUMBERS,
    computeDaysOfWeekUpdate,
    getEffectiveDaysOfWeek,
    type IsoDayOfWeek,
} from './daysOfWeekFilterUtils'

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

/** PostHog relative-date strings → a composer selection. Named periods resolve through
 *  `dateMapping`, so the composer's chip names and the query vocabulary can't drift. */
export function selectionForDateRange(dateFrom: string, dateTo: string | null | undefined): DateRangeComposerSelection {
    const rolling = !dateTo && dateFrom.match(ROLLING_DATE_FROM)
    if (rolling) {
        return { kind: 'rolling', count: parseInt(rolling[1], 10), unit: UNIT_BY_LETTER[rolling[2]] }
    }
    const named = dateMapping.find(({ values }) => values[0] === dateFrom && (values[1] ?? null) === (dateTo ?? null))
    if (named) {
        return { kind: 'fixed', name: named.key }
    }
    const start = dayjs(dateFrom)
    if (start.isValid()) {
        const end = dateTo ? dayjs(dateTo) : dayjs()
        return { kind: 'custom', start: start.toDate(), end: end.isValid() ? end.toDate() : new Date() }
    }
    return { kind: 'rolling', count: 7, unit: 'days' }
}

function formatCustomDate(date: Date): string {
    const hasTime = date.getHours() !== 0 || date.getMinutes() !== 0
    return dayjs(date).format(hasTime ? 'YYYY-MM-DDTHH:mm:ss' : 'YYYY-MM-DD')
}

/** Composer selection → the PostHog date range strings to persist. */
export function dateRangeForSelection(selection: DateRangeComposerSelection): Pick<DateRange, 'date_from' | 'date_to'> {
    if (selection.kind === 'rolling') {
        return { date_from: `-${selection.count}${LETTER_BY_UNIT[selection.unit]}`, date_to: null }
    }
    if (selection.kind === 'fixed') {
        const named = dateMapping.find(({ key }) => key === selection.name)
        return { date_from: named?.values[0] ?? null, date_to: named?.values[1] ?? null }
    }
    return { date_from: formatCustomDate(selection.start), date_to: formatCustomDate(selection.end) }
}

function shortExclusionsLabel(summary: string): string {
    const parts = summary.replace('Excluding ', '').split(', ')
    return parts.length > 1 ? `excl. ${parts[0]} +${parts.length - 1}` : `excl. ${parts[0]}`
}

const LEMON_SKIN_PROPS = { 'data-lemon-skin': 'true' }

type InsightDateFilterComposerProps = {
    disabled: boolean
}

export function InsightDateFilterComposer({ disabled }: InsightDateFilterComposerProps): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { dateRange, querySource, trendsFilter, isTrends, isRetention } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange, updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const [open, setOpen] = useState(false)

    const selection = selectionForDateRange(dateRange?.date_from ?? '-7d', dateRange?.date_to)

    // The composer speaks excluded days; the query schema stores included days.
    const includedDays = getEffectiveDaysOfWeek(dateRange, trendsFilter)
    const excludedDays = includedDays.length === 0 ? [] : ALL_DAY_NUMBERS.filter((day) => !includedDays.includes(day))
    const exclusions: DateRangeComposerExclusions = {
        days: isTrends ? excludedDays.map(String) : [],
        incomplete: !isRetention && !!dateRange?.excludeIncompletePeriods,
    }
    const handleExclusionsChange = (next: DateRangeComposerExclusions): void => {
        if (isTrends && next.days.join(',') !== exclusions.days.join(',')) {
            const excluded = next.days.map(Number) as IsoDayOfWeek[]
            const included =
                excluded.length === 0
                    ? []
                    : (ALL_DAY_NUMBERS.filter((day) => !excluded.includes(day)) as IsoDayOfWeek[])
            updateQuerySource(computeDaysOfWeekUpdate(included, querySource, dateRange))
        }
        if (!isRetention && next.incomplete !== exclusions.incomplete) {
            updateDateRange({ excludeIncompletePeriods: next.incomplete ? true : null }, true)
        }
    }

    const summary = composerExclusionsSummary(exclusions)

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
                {composerSelectionLabel(selection)}
                {summary && (
                    <span className="text-muted-foreground font-normal">· {shortExclusionsLabel(summary)}</span>
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
                        updateDateRange(dateRangeForSelection(next), true)
                        if (next.kind !== 'rolling') {
                            setOpen(false)
                        }
                    }}
                    exclusions={exclusions}
                    onExclusionsChange={handleExclusionsChange}
                    showExcludedDays={isTrends}
                    showIncompletePeriod={!isRetention}
                    exactTime={dateRange?.explicitDate ?? false}
                    onExactTimeChange={(checked) => updateDateRange({ explicitDate: checked }, true)}
                    portalProps={LEMON_SKIN_PROPS as unknown as DateRangeComposerProps['portalProps']}
                />
            </QuillPopoverContent>
        </QuillPopover>
    )
}
