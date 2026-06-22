import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { Day, useCalendar } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

export interface FilterPickerDateValueProps {
    /** Receives the picked day as an ISO `YYYY-MM-DD` string. */
    onSelect: (isoDate: string) => void
}

// Single-date inline calendar for the before/after/exact date operators. Quill's DateTimePicker is a
// range picker with quick-range presets, which don't map onto a single-value operator — so we render a
// minimal day grid off the headless useCalendar hook instead.
export function FilterPickerDateValue({ onSelect }: FilterPickerDateValueProps): JSX.Element {
    const { calendar, viewing, viewPreviousMonth, viewNextMonth } = useCalendar({ weekStartsOn: Day.MONDAY })
    const weeks = calendar[0] ?? []
    const today = dayjs()
    const weekdayLabels = (weeks[0] ?? []).map((date) => dayjs(date).format('dd'))

    return (
        <div className="w-64 p-1">
            <div className="flex items-center justify-between px-1 pb-1">
                <button
                    type="button"
                    aria-label="Previous month"
                    className="rounded-md p-1 text-tertiary hover:bg-fill-button-tertiary-hover hover:text-primary"
                    onClick={viewPreviousMonth}
                >
                    <IconChevronLeft className="text-base" />
                </button>
                <span className="text-sm font-medium">{dayjs(viewing).format('MMMM YYYY')}</span>
                <button
                    type="button"
                    aria-label="Next month"
                    className="rounded-md p-1 text-tertiary hover:bg-fill-button-tertiary-hover hover:text-primary"
                    onClick={viewNextMonth}
                >
                    <IconChevronRight className="text-base" />
                </button>
            </div>
            <div className="grid grid-cols-7 gap-0.5 text-center text-xxs font-semibold uppercase text-tertiary">
                {weekdayLabels.map((label, index) => (
                    <span key={index}>{label}</span>
                ))}
            </div>
            <div className="grid grid-cols-7 gap-0.5">
                {weeks.flat().map((date) => {
                    const isOutsideMonth = dayjs(date).month() !== dayjs(viewing).month()
                    const isToday = dayjs(date).isSame(today, 'day')
                    return (
                        <button
                            key={date.getTime()}
                            type="button"
                            aria-label={dayjs(date).format('LL')}
                            className={cn(
                                'flex h-7 items-center justify-center rounded-md text-sm outline-none',
                                'hover:bg-fill-button-tertiary-hover focus:bg-fill-button-tertiary-hover',
                                isOutsideMonth && 'text-tertiary',
                                isToday && 'font-semibold text-accent'
                            )}
                            onClick={() => onSelect(dayjs(date).format('YYYY-MM-DD'))}
                        >
                            {dayjs(date).date()}
                        </button>
                    )
                })}
            </div>
        </div>
    )
}
