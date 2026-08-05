import { getDate, getDaysInMonth, getHours, getMinutes, getMonth, getYear } from 'date-fns'
import * as React from 'react'

import {
    InputGroup,
    InputGroupNumberInput,
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@posthog/quill-primitives'

export type DateFormatOrder = 'MDY' | 'DMY' | 'YMD'

export const DATE_FORMAT_LABELS: Record<DateFormatOrder, string> = {
    MDY: 'MM/DD/YY',
    DMY: 'DD/MM/YY',
    YMD: 'YY-MM-DD',
}

const PAD_2 = { minimumIntegerDigits: 2 } as const

export interface SegmentedDateInputProps {
    date: Date
    maxDate: Date
    onChange: (date: Date) => void
    dateFormat: DateFormatOrder
    /** Show hour/minute segments alongside the date. */
    showTime: boolean
}

/**
 * Segmented numeric date (+ optional time) entry shared by DatePicker and DateTimePicker.
 * Edits are debounced before committing so partially-typed values don't fire onChange.
 * Time-format follow-ups (12/24h, granularity) belong here so both pickers inherit them.
 */
export function SegmentedDateInput({
    date,
    maxDate,
    onChange,
    dateFormat,
    showTime,
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

    const segmentClass = 'w-7 flex-none text-center tabular-nums p-0'
    const separatorClass = 'text-xs text-muted-foreground select-none'
    const sep = dateFormat === 'YMD' ? '-' : '/'

    const maxYear = getYear(maxDate) % 100
    const atMaxYear = year === maxYear
    const maxMonth = atMaxYear ? getMonth(maxDate) + 1 : 12
    const atMaxMonth = atMaxYear && month === maxMonth
    const maxDay = atMaxMonth ? getDate(maxDate) : getDaysInMonth(new Date(2000 + year, month - 1))

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
                            value={hour}
                            onValueChange={set(setHour)}
                            min={0}
                            max={23}
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
                    </InputGroup>
                )}
            </div>
        </TooltipProvider>
    )
}
