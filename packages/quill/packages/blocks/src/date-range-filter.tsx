import { subDays } from 'date-fns'
import * as React from 'react'

import {
    CUSTOM_RANGE,
    DateTimePicker,
    type DateFormatOrder,
    type DateTimeValue,
    type Day,
} from '@posthog/quill-components'
import { Button, Popover, PopoverContent, PopoverTrigger, cn } from '@posthog/quill-primitives'

export interface DateRangeFilterPreset<T = unknown> {
    id: string
    label: string
    /** Opaque payload couriered back through `onPresetSelect`; the block never interprets it. */
    value?: T
    /** Preview span shown in the custom calendar while this preset is active. */
    previewStart?: (now: Date) => Date
    previewEnd?: (now: Date) => Date
}

export interface DateRangeFilterProps<T = unknown> {
    presets: DateRangeFilterPreset<T>[]
    selectedPresetId?: string | null
    /** Selecting a preset applies immediately and closes the popover. */
    onPresetSelect: (preset: DateRangeFilterPreset<T>) => void
    /** Enables the custom-range calendar view. Omit to hide the "Custom range…" row. */
    onCustomApply?: (start: Date, end: Date) => void
    /** Marks the current value as a custom range: highlights the row and opens straight to the calendar. */
    customActive?: boolean
    customStart?: Date
    customEnd?: Date
    customLabel?: string
    /** Text for the default trigger button; ignored when `trigger` is provided. */
    label?: React.ReactNode
    /** Trigger element override; defaults to an outline Button showing `label`. */
    trigger?: React.ReactElement
    disabled?: boolean
    /** Host content pinned below the preset list (hidden in the calendar view). */
    listFooter?: React.ReactNode
    showTime?: boolean
    weekStartsOn?: Day
    dateFormat?: DateFormatOrder
    minDate?: Date
    maxDate?: Date
    defaultOpen?: boolean
    className?: string
}

/** Presets-first date filter: a trigger opening a quick-range list (instant apply), with an
 *  optional calendar range picker revealed behind a "Custom range…" row. The block owns the
 *  interaction shell only — what a preset *means* (and how it persists) stays with the host,
 *  which gets its `value` payload back verbatim on selection. */
export function DateRangeFilter<T = unknown>({
    presets,
    selectedPresetId,
    onPresetSelect,
    onCustomApply,
    customActive = false,
    customStart,
    customEnd,
    customLabel = 'Custom range…',
    label,
    trigger,
    disabled = false,
    listFooter,
    showTime = false,
    weekStartsOn,
    dateFormat,
    minDate,
    maxDate,
    defaultOpen = false,
    className,
}: DateRangeFilterProps<T>): React.ReactElement {
    const hasCustom = onCustomApply != null
    const [open, setOpen] = React.useState(defaultOpen)
    const [customView, setCustomView] = React.useState(defaultOpen && customActive && hasCustom)

    const handleOpenChange = (nextOpen: boolean): void => {
        if (nextOpen) {
            // Start on the preset list; jump straight to the calendar only if a custom range is active
            setCustomView(customActive && hasCustom)
        }
        setOpen(nextOpen)
    }

    const calendarValue = React.useMemo((): DateTimeValue => {
        const now = new Date()
        if (customActive && customStart && customEnd) {
            return { start: customStart, end: customEnd, range: CUSTOM_RANGE }
        }
        const selected = presets.find((preset) => preset.id === selectedPresetId)
        return {
            start: selected?.previewStart?.(now) ?? subDays(now, 7),
            end: selected?.previewEnd?.(now) ?? now,
            range: CUSTOM_RANGE,
        }
    }, [customActive, customStart, customEnd, presets, selectedPresetId])

    return (
        <Popover open={open} onOpenChange={handleOpenChange}>
            <PopoverTrigger
                render={
                    trigger ?? (
                        <Button variant="outline" disabled={disabled} data-slot="date-range-filter-trigger">
                            {label}
                        </Button>
                    )
                }
            />
            <PopoverContent
                align="start"
                className={cn('w-auto overflow-hidden p-0', className)}
                data-slot="date-range-filter"
            >
                {customView && hasCustom ? (
                    <DateTimePicker
                        value={calendarValue}
                        ranges={[]}
                        showHeader={false}
                        showTime={showTime}
                        weekStartsOn={weekStartsOn}
                        dateFormat={dateFormat}
                        minDate={minDate}
                        maxDate={maxDate}
                        onApply={(value) => {
                            onCustomApply(value.start, value.end)
                            setOpen(false)
                        }}
                        onCancel={() => setCustomView(false)}
                        className="rounded-none shadow-none ring-0"
                    />
                ) : (
                    <div className="flex flex-col" data-slot="date-range-filter-list">
                        <div className="flex max-h-100 flex-col overflow-y-auto p-1">
                            {presets.map((preset) => (
                                <Button
                                    key={preset.id}
                                    variant="default"
                                    left
                                    className="w-full justify-start"
                                    aria-selected={preset.id === selectedPresetId}
                                    onClick={() => {
                                        onPresetSelect(preset)
                                        setOpen(false)
                                    }}
                                    data-attr={`date-range-filter-preset-${preset.id}`}
                                >
                                    {preset.label}
                                </Button>
                            ))}
                            {hasCustom && (
                                <Button
                                    variant="default"
                                    left
                                    className="w-full justify-start"
                                    aria-selected={customActive}
                                    onClick={() => setCustomView(true)}
                                    data-attr="date-range-filter-custom"
                                >
                                    {customLabel}
                                </Button>
                            )}
                        </div>
                        {listFooter != null && (
                            <div className="border-t" data-slot="date-range-filter-footer">
                                {listFooter}
                            </div>
                        )}
                    </div>
                )}
            </PopoverContent>
        </Popover>
    )
}
