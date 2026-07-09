import { format, getHours, getMinutes, getMonth, getYear, startOfDay } from 'date-fns'
import { SettingsIcon } from 'lucide-react'
import * as React from 'react'

import { Badge, Button, Separator, Switch, cn } from '@posthog/quill-primitives'

import { Calendar } from './calendar-grid'
import { SegmentedDateInput, type DateFormatOrder, type HourCycle } from './segmented-date-input'
import { Day } from './use-calendar'

// Minute precision, no seconds — deliberately differs from DateTimePicker's HH:mm:ss; don't unify.
const DATE_TIME_FORMATS: Record<DateFormatOrder, string> = {
    MDY: 'MM/dd/yy HH:mm',
    DMY: 'dd/MM/yy HH:mm',
    YMD: 'yy-MM-dd HH:mm',
}
const DATE_TIME_FORMATS_12H: Record<DateFormatOrder, string> = {
    MDY: 'MM/dd/yy h:mm a',
    DMY: 'dd/MM/yy h:mm a',
    YMD: 'yy-MM-dd h:mm a',
}
const DATE_ONLY_FORMATS: Record<DateFormatOrder, string> = {
    MDY: 'MM/dd/yy',
    DMY: 'dd/MM/yy',
    YMD: 'yy-MM-dd',
}

export interface DatePickerProps {
    value: Date
    onApply: (value: Date) => void
    onCancel?: () => void
    minDate?: Date
    /** Latest selectable date. Omit for no upper bound (calendar navigation still caps ten years out). */
    maxDate?: Date
    dateFormat?: DateFormatOrder
    weekStartsOn?: Day
    onDateTimeSettings?: () => void
    /** Include time in the value initially. When off, the value is floored to the start of the day. */
    showTime?: boolean
    /** Render the "Include time" toggle so the user can switch time on and off. Defaults to `showTime`. Set false for a fixed precision. */
    showTimeToggle?: boolean
    /** Fired when the "Include time" toggle changes. */
    onIncludeTimeChange?: (includeTime: boolean) => void
    /** 12 renders 1-12 hour entry with an AM/PM toggle; 24 (default) renders 0-23. */
    hourCycle?: HourCycle
    className?: string
}


export function DatePicker({
    value,
    onApply,
    onCancel,
    minDate,
    maxDate,
    dateFormat = 'MDY',
    weekStartsOn,
    onDateTimeSettings,
    showTime = false,
    showTimeToggle = showTime,
    onIncludeTimeChange,
    hourCycle = 24,
    className,
}: DatePickerProps): React.ReactElement {
    const [selected, setSelected] = React.useState<Date>(value)
    const [includeTime, setIncludeTime] = React.useState<boolean>(showTime)
    const [viewing, setViewing] = React.useState<Date>(new Date(getYear(value), getMonth(value), 1))
    // Instance-scoped so two DatePickers on one page don't share a label association.
    const includeTimeId = React.useId()

    const handleSelect = (date: Date): void => {
        const next = new Date(
            date.getFullYear(),
            date.getMonth(),
            date.getDate(),
            includeTime ? getHours(selected) : 0,
            includeTime ? getMinutes(selected) : 0
        )
        setSelected(next)
    }

    // The calendar disables out-of-bounds days and the segmented input caps its date segments at
    // maxDate, but neither bounds the time of day — a typed time (or the time carried over from a
    // previous selection) can still land outside minDate/maxDate on a boundary day. Clamping here
    // guarantees the value never escapes the advertised bounds. Date-only values clamp against the
    // bounds' days, not their times, so the calendar's day-granular rules stay authoritative.
    const clampToBounds = (date: Date, dayGranular: boolean): Date => {
        const min = minDate ? (dayGranular ? startOfDay(minDate) : minDate) : undefined
        const max = maxDate ? (dayGranular ? startOfDay(maxDate) : maxDate) : undefined
        if (min && date.getTime() < min.getTime()) {
            return min
        }
        if (max && date.getTime() > max.getTime()) {
            return max
        }
        return date
    }

    const handleInputChange = (next: Date): void => {
        const clamped = clampToBounds(next, !includeTime)
        if (clamped.getTime() === selected.getTime()) {
            return
        }
        setSelected(clamped)
        setViewing(new Date(getYear(clamped), getMonth(clamped), 1))
    }

    const handleIncludeTimeChange = (next: boolean): void => {
        setIncludeTime(next)
        onIncludeTimeChange?.(next)
    }

    const handleApply = (): void => {
        onApply(includeTime ? clampToBounds(selected, false) : clampToBounds(startOfDay(selected), true))
    }

    const timeFormat = hourCycle === 12 ? DATE_TIME_FORMATS_12H[dateFormat] : DATE_TIME_FORMATS[dateFormat]
    const presentational = format(selected, includeTime ? timeFormat : DATE_ONLY_FORMATS[dateFormat])

    return (
        <div
            className={cn(
                'bg-card text-foreground rounded-lg shadow-md ring-1 ring-foreground/10 overflow-hidden w-[15rem]',
                className
            )}
        >
            <div className="flex items-center gap-2 px-2 py-1 bg-muted/30 border-b border-border rounded-t-lg">
                <span className="text-[10px] text-muted-foreground uppercase tracking-wide">Choose date</span>
                {(minDate || maxDate) && (
                    <div className="flex items-center gap-1 ml-auto">
                        {minDate && (
                            <Badge variant="default" className="text-[10px] px-1.5 py-0">
                                Min: {format(minDate, 'MMM d, yy')}
                            </Badge>
                        )}
                        {maxDate && (
                            <Badge variant="default" className="text-[10px] px-1.5 py-0">
                                Max: {format(maxDate, 'MMM d, yy')}
                            </Badge>
                        )}
                    </div>
                )}
            </div>

            <div className="flex justify-center items-center px-3 pt-3 pb-1">
                <div className="flex items-center gap-1.5">
                    {onDateTimeSettings && (
                        <Button
                            size="icon-xs"
                            onClick={onDateTimeSettings}
                            aria-label="Date and time settings"
                            title="Date and time settings"
                            className="text-muted-foreground hover:text-foreground"
                        >
                            <SettingsIcon />
                        </Button>
                    )}
                    <SegmentedDateInput
                        date={selected}
                        maxDate={maxDate}
                        onChange={handleInputChange}
                        dateFormat={dateFormat}
                        showTime={includeTime}
                        hourCycle={hourCycle}
                    />
                </div>
            </div>

            <div className="p-2 flex justify-center">
                <Calendar
                    defaultViewing={viewing}
                    startDate={selected}
                    endDate={selected}
                    minDate={minDate}
                    maxDate={maxDate}
                    onSelect={handleSelect}
                    onViewChange={setViewing}
                    weekStartsOn={weekStartsOn}
                />
            </div>

            {showTimeToggle && (
                <div className="flex items-center gap-2 px-3 py-1.5 border-t border-border">
                    <Switch
                        checked={includeTime}
                        onCheckedChange={handleIncludeTimeChange}
                        aria-label="Include time"
                        id={includeTimeId}
                        data-attr="date-picker-include-time"
                    />
                    <label htmlFor={includeTimeId} className="text-xs text-muted-foreground select-none">
                        Include time
                    </label>
                </div>
            )}

            <Separator />

            <div className="flex justify-end px-3 py-2 items-center gap-2 bg-muted/30">
                <span className="text-[10px] text-muted-foreground tabular-nums mr-auto">{presentational}</span>
                {onCancel ? (
                    <Button variant="outline" size="sm" onClick={onCancel} aria-label="Cancel" data-attr="date-picker-cancel">
                        Cancel
                    </Button>
                ) : null}
                <Button
                    variant="primary"
                    size="sm"
                    aria-label="Apply date"
                    title="Apply date"
                    onClick={handleApply}
                    data-attr="date-picker-apply"
                >
                    Apply
                </Button>
            </div>
        </div>
    )
}
