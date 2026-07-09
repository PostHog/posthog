import { getDate, getDaysInMonth, getHours, getMinutes, getMonth, getYear } from 'date-fns'
import * as React from 'react'

import {
    InputGroup,
    InputGroupButton,
    InputGroupNumberInput,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@posthog/quill-primitives'

export type DateFormatOrder = 'MDY' | 'DMY' | 'YMD'
export type HourCycle = 12 | 24

export const DATE_FORMAT_LABELS: Record<DateFormatOrder, string> = {
    MDY: 'MM/DD/YY',
    DMY: 'DD/MM/YY',
    YMD: 'YY-MM-DD',
}

const PAD_2 = { minimumIntegerDigits: 2 } as const

export interface SegmentedDateInputProps {
    date: Date
    /** Upper bound for the date segments. Omit for no upper bound (year segment still tops out at 2099). */
    maxDate?: Date
    onChange: (date: Date) => void
    dateFormat: DateFormatOrder
    /** Show hour/minute segments alongside the date. */
    showTime: boolean
    /** 12 renders a 1-12 hour segment plus an AM/PM toggle; 24 renders 0-23. */
    hourCycle?: HourCycle
}

/**
 * Segmented numeric date (+ optional time) entry shared by DatePicker and DateTimePicker.
 * Edits are debounced before committing so partially-typed values don't fire onChange.
 * Time-format follow-ups (granularity) belong here so both pickers inherit them.
 */
export function SegmentedDateInput({
    date,
    maxDate,
    onChange,
    dateFormat,
    showTime,
    hourCycle = 24,
}: SegmentedDateInputProps): React.ReactElement {
    const [month, setMonth] = React.useState(getMonth(date) + 1)
    const [day, setDay] = React.useState(getDate(date))
    const [year, setYear] = React.useState(getYear(date) % 100)
    const [hour, setHour] = React.useState(getHours(date))
    const [minute, setMinute] = React.useState(getMinutes(date))

    const onChangeRef = React.useRef(onChange)
    React.useEffect(() => {
        onChangeRef.current = onChange
    }, [onChange])

    React.useEffect(() => {
        setMonth(getMonth(date) + 1)
        setDay(getDate(date))
        setYear(getYear(date) % 100)
        setHour(getHours(date))
        setMinute(getMinutes(date))
    }, [date])

    const touched = React.useRef(false)
    React.useEffect(() => {
        if (!touched.current) {
            return
        }
        const handle = setTimeout(() => {
            // Two-digit year input: 2000-2099 only. Acceptable for analytics date ranges;
            // a value outside that window can't be entered via the segments (silent, not an error).
            onChangeRef.current(new Date(2000 + year, month - 1, day, hour, minute))
            touched.current = false
        }, 400)
        return () => clearTimeout(handle)
    }, [month, day, year, hour, minute])

    const set = (setter: React.Dispatch<React.SetStateAction<number>>) => (v: number | null) => {
        if (v === null) {
            return
        }
        touched.current = true
        setter(v)
    }

    // Hour state is always 0-23; the 12-hour cycle only changes how it's displayed and entered.
    const isPM = hour >= 12
    const setHour12 = (v: number | null): void => {
        if (v === null) {
            return
        }
        touched.current = true
        setHour((prev) => (v % 12) + (prev >= 12 ? 12 : 0))
    }
    const toggleMeridiem = (): void => {
        touched.current = true
        setHour((prev) => (prev >= 12 ? prev - 12 : prev + 12))
    }

    const segmentClass = 'w-7 flex-none text-center tabular-nums p-0'
    const separatorClass = 'text-xs text-muted-foreground select-none'
    const sep = dateFormat === 'YMD' ? '-' : '/'

    const maxYear = maxDate ? getYear(maxDate) % 100 : 99
    const atMaxYear = !!maxDate && year === maxYear
    const maxMonth = maxDate && atMaxYear ? getMonth(maxDate) + 1 : 12
    const atMaxMonth = atMaxYear && month === maxMonth
    const maxDay = maxDate && atMaxMonth ? getDate(maxDate) : getDaysInMonth(new Date(2000 + year, month - 1))

    const monthSegment = (
        <InputGroupNumberInput
            key="month"
            aria-label="Month"
            value={month}
            onValueChange={set(setMonth)}
            min={1}
            max={maxMonth}
            format={PAD_2}
            className={segmentClass}
        />
    )
    const daySegment = (
        <InputGroupNumberInput
            key="day"
            aria-label="Day"
            value={day}
            onValueChange={set(setDay)}
            min={1}
            max={maxDay}
            format={PAD_2}
            className={segmentClass}
        />
    )
    const yearSegment = (
        <InputGroupNumberInput
            key="year"
            aria-label="Year"
            value={year}
            onValueChange={set(setYear)}
            min={0}
            max={maxYear}
            format={PAD_2}
            className={segmentClass}
        />
    )

    const dateSegments =
        dateFormat === 'DMY'
            ? [daySegment, monthSegment, yearSegment]
            : dateFormat === 'YMD'
              ? [yearSegment, monthSegment, daySegment]
              : [monthSegment, daySegment, yearSegment]

    return (
        <TooltipProvider>
            <div className="flex items-center gap-2">
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <InputGroup className="w-auto px-1.5">
                                {dateSegments.map((segment, i) => (
                                    <React.Fragment key={i}>
                                        {i > 0 && <span className={separatorClass}>{sep}</span>}
                                        {segment}
                                    </React.Fragment>
                                ))}
                            </InputGroup>
                        }
                    />
                    <TooltipContent>{DATE_FORMAT_LABELS[dateFormat]}</TooltipContent>
                </Tooltip>

                {showTime && (
                    <InputGroup className="w-auto px-1.5">
                        <InputGroupNumberInput
                            aria-label="Hour"
                            value={hourCycle === 12 ? hour % 12 || 12 : hour}
                            onValueChange={hourCycle === 12 ? setHour12 : set(setHour)}
                            min={hourCycle === 12 ? 1 : 0}
                            max={hourCycle === 12 ? 12 : 23}
                            format={PAD_2}
                            className={segmentClass}
                        />
                        <span className={separatorClass}>:</span>
                        <InputGroupNumberInput
                            aria-label="Minute"
                            value={minute}
                            onValueChange={set(setMinute)}
                            min={0}
                            max={59}
                            format={PAD_2}
                            className={segmentClass}
                        />
                        {hourCycle === 12 && (
                            <InputGroupButton
                                aria-label={isPM ? 'Switch to AM' : 'Switch to PM'}
                                title={isPM ? 'Switch to AM' : 'Switch to PM'}
                                onClick={toggleMeridiem}
                                data-attr="segmented-date-input-meridiem"
                                className="tabular-nums"
                            >
                                {isPM ? 'PM' : 'AM'}
                            </InputGroupButton>
                        )}
                    </InputGroup>
                )}
            </div>
        </TooltipProvider>
    )
}
