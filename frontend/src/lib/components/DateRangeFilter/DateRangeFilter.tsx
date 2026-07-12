import { useMemo, useState } from 'react'

import {
    CUSTOM_RANGE,
    DateTimePicker,
    Popover,
    PopoverContent,
    PopoverTrigger,
    type DateTimeRange,
    type DateTimeValue,
    type Day,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

export interface DateRangePreset<T = unknown> {
    id: string
    label: string
    /** Opaque payload couriered back through `onPresetSelect`; never interpreted here. */
    value?: T
    /** Preview span shown in the custom calendar while this preset is active. */
    previewStart?: (now: Date) => Date
    previewEnd?: (now: Date) => Date
}

export interface DateRangeFilterProps<T = unknown> {
    presets: DateRangePreset<T>[]
    selectedPresetId?: string | null
    /** Presets apply immediately on click and close the popover. */
    onPresetSelect: (preset: DateRangePreset<T>) => void
    /** Custom calendar applies commit concrete browser-local dates. */
    onCustomApply: (start: Date, end: Date) => void
    /** Marks the current value as a custom range: the popover opens straight to the calendar. */
    customActive?: boolean
    customStart?: Date
    customEnd?: Date
    trigger: React.ReactElement
    /** Host content in the picker's actions bar (e.g. an exclusions control); stays reachable in the collapsed list view. */
    footerExtra?: React.ReactNode
    weekStartsOn?: Day
    /** Extra props for the popover surface (portaled to <body>) — e.g. skin opt-in data attributes. */
    contentProps?: React.ComponentProps<typeof PopoverContent>
}

/** Presets-first date range filter: a trigger opening quill's `DateTimePicker` in `presetsFirst`
 *  mode. Owns only the popover shell and the preset payload routing — what a preset *means* stays
 *  with the host, which gets its `value` back verbatim on selection. */
export function DateRangeFilter<T = unknown>({
    presets,
    selectedPresetId,
    onPresetSelect,
    onCustomApply,
    customActive = false,
    customStart,
    customEnd,
    trigger,
    footerExtra,
    weekStartsOn,
    contentProps,
}: DateRangeFilterProps<T>): JSX.Element {
    const [open, setOpen] = useState(false)
    // Base UI keeps the popup mounted across closes; remount the picker per open so its staged
    // state and collapsed/expanded view re-derive from the current value instead of going stale.
    const [openKey, setOpenKey] = useState(0)
    const handleOpenChange = (nextOpen: boolean): void => {
        if (nextOpen) {
            setOpenKey((prev) => prev + 1)
        }
        setOpen(nextOpen)
    }

    // Picker-rail mirror of `presets`: numeric ids are 1-based indexes (0 is CUSTOM_RANGE)
    const ranges = useMemo(
        (): DateTimeRange[] =>
            presets.map((preset, index) => ({
                id: index + 1,
                name: preset.label,
                rangeSetter: (now: Date) => preset.previewStart?.(now) ?? dayjs(now).subtract(7, 'day').toDate(),
                endSetter: preset.previewEnd,
            })),
        [presets]
    )

    const pickerValue = useMemo((): DateTimeValue => {
        const now = new Date()
        if (customActive && customStart && customEnd) {
            return { start: customStart, end: customEnd, range: CUSTOM_RANGE }
        }
        const selectedIndex = presets.findIndex((preset) => preset.id === selectedPresetId)
        const selected = selectedIndex >= 0 ? presets[selectedIndex] : undefined
        return {
            start: selected?.previewStart?.(now) ?? dayjs(now).subtract(7, 'day').toDate(),
            end: selected?.previewEnd?.(now) ?? now,
            range: selectedIndex >= 0 ? ranges[selectedIndex] : CUSTOM_RANGE,
        }
    }, [customActive, customStart, customEnd, presets, selectedPresetId, ranges])

    const handleApply = (applied: DateTimeValue): void => {
        const preset = applied.range.id !== CUSTOM_RANGE.id ? presets[applied.range.id - 1] : undefined
        if (preset) {
            onPresetSelect(preset)
        } else {
            onCustomApply(applied.start, applied.end)
        }
        setOpen(false)
    }

    return (
        <Popover open={open} onOpenChange={handleOpenChange}>
            <PopoverTrigger render={trigger} />
            <PopoverContent
                align="start"
                // Pinned: expanding the calendar must not shift the preset list under the cursor
                collisionAvoidance={{ align: 'none' }}
                {...contentProps}
                className={`w-auto overflow-hidden border-none p-0 shadow-none ring-0 ${contentProps?.className ?? ''}`}
            >
                <DateTimePicker
                    key={openKey}
                    value={pickerValue}
                    ranges={ranges}
                    presetsFirst
                    showHeader={false}
                    showTime={false}
                    weekStartsOn={weekStartsOn}
                    footerExtra={footerExtra}
                    onApply={handleApply}
                />
            </PopoverContent>
        </Popover>
    )
}
