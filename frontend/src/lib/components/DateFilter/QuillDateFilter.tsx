import { useMemo, useState } from 'react'

import { DateTimePicker, Label, Switch } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import {
    DateRangePresetsPanel,
    selectionKeyOf,
    valueForSelection,
    type DataAttributeProps,
    type DateRangeChip,
    type DateRangeSelection,
} from './DateRangePresetsPanel'

export interface QuillDateFilterProps {
    selection: DateRangeSelection
    /** Chip and stepper picks — immediate, not staged. */
    onSelectionChange: (selection: DateRangeSelection) => void
    /** Calendar Apply — `includesTime` reflects the "Include time" toggle. */
    onApplyCustom: (selection: Extract<DateRangeSelection, { kind: 'custom' }>) => void
    shortChips?: DateRangeChip[]
    namedChips?: string[]
    weekStartsOn?: 0 | 1
    presetsFooter?: React.ReactNode
    portalProps?: DataAttributeProps
}

/** The experimental chip-based date filter: the presets panel beside a stock quill DateTimePicker,
 * with the calendar collapsed behind the panel's "Custom range…" row. Composed app-side so the
 * design system stays untouched while this is an experiment. */
export function QuillDateFilter({
    selection,
    onSelectionChange,
    onApplyCustom,
    shortChips,
    namedChips,
    weekStartsOn = 1,
    presetsFooter,
    portalProps,
}: QuillDateFilterProps): JSX.Element {
    const [calendarOpen, setCalendarOpen] = useState(false)
    const [includeTime, setIncludeTime] = useState(false)

    const selectionKey = selectionKeyOf(selection)
    // Frozen per selection so chip titles and the calendar seed agree across re-renders.
    const now = useMemo(() => dayjs(), [selectionKey]) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div
            className="flex w-max overflow-hidden rounded-lg bg-card text-foreground shadow-md ring-1 ring-foreground/10"
            data-attr="quill-date-filter"
        >
            <DateRangePresetsPanel
                selection={selection}
                onSelectionChange={onSelectionChange}
                shortChips={shortChips}
                namedChips={namedChips}
                now={now}
                weekStartsOn={weekStartsOn}
                calendarOpen={calendarOpen}
                onCalendarOpenChange={setCalendarOpen}
                portalProps={portalProps}
                footer={
                    <>
                        {calendarOpen && (
                            <div className="flex h-8 items-center justify-between gap-2 px-2">
                                <Label htmlFor="date-filter-include-time">Include time</Label>
                                <Switch
                                    id="date-filter-include-time"
                                    size="sm"
                                    checked={includeTime}
                                    onCheckedChange={setIncludeTime}
                                />
                            </div>
                        )}
                        {presetsFooter}
                    </>
                }
            />
            {calendarOpen && (
                <DateTimePicker
                    // The picker stages from `value` at mount only — remount to reseed
                    key={`${selectionKey}-${includeTime ? 'time' : 'day'}`}
                    ranges={[]}
                    showHeader={false}
                    showTime={includeTime}
                    weekStartsOn={weekStartsOn}
                    value={valueForSelection(selection, now, weekStartsOn)}
                    onApply={({ start, end }) => {
                        onApplyCustom({ kind: 'custom', start, end, includesTime: includeTime })
                        setCalendarOpen(false)
                    }}
                    onCancel={() => setCalendarOpen(false)}
                    // flex-col + separator mt-auto pin Cancel/Apply to the bottom when the panel is taller
                    className="flex shrink-0 flex-col rounded-none border-l border-border shadow-none ring-0 lg:w-auto [&>[data-slot=separator]]:mt-auto"
                />
            )}
        </div>
    )
}
