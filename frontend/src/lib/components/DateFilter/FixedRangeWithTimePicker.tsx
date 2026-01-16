import clsx from 'clsx'
import { useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendar } from 'lib/lemon-ui/LemonCalendar/LemonCalendar'

const DATE_TIME_FORMAT_24H = 'MMM D, YYYY HH:mm'
const DATE_TIME_FORMAT_12H = 'MMM D, YYYY h:mm A'

export interface FixedRangeWithTimePickerProps {
    rangeDateFrom: dayjs.Dayjs | null
    rangeDateTo: dayjs.Dayjs | null
    setDate: (dateFrom: string | null, dateTo: string | null, keepPopoverOpen: boolean, explicitDate: boolean) => void
    onClose: () => void
    /** Use 24-hour format instead of 12-hour with AM/PM */
    use24HourFormat?: boolean
    /** Whether to show the "Include time?" toggle */
    showTimeToggle?: boolean
    /** Callback when time toggle is changed */
    onToggleTime?: (includeTime: boolean) => void
}

export function FixedRangeWithTimePicker({
    rangeDateFrom,
    rangeDateTo,
    setDate,
    onClose,
    use24HourFormat = false,
    showTimeToggle,
    onToggleTime,
}: FixedRangeWithTimePickerProps): JSX.Element {
    const [selectingStart, setSelectingStart] = useState(true)
    const [localFrom, setLocalFrom] = useState<dayjs.Dayjs | null>(rangeDateFrom)
    const [localTo, setLocalTo] = useState<dayjs.Dayjs | null>(rangeDateTo)

    const handleApply = (): void => {
        if (localFrom && localTo) {
            const [from, to] = localFrom.isBefore(localTo) ? [localFrom, localTo] : [localTo, localFrom]
            setDate(from.format('YYYY-MM-DDTHH:mm:ss'), to.format('YYYY-MM-DDTHH:mm:ss'), false, true)
        }
    }

    return (
        <div className="LemonCalendarRangeWithTime" data-attr="lemon-calendar-range-with-time">
            <div className="flex justify-between border-b p-2 pb-4">
                <h3 className="text-base mb-0">Select a date and time range</h3>
                <LemonButton icon={<IconX />} size="small" noPadding onClick={onClose} aria-label="close" />
            </div>
            <div className="flex gap-2 p-2 border-b">
                <LemonButton
                    type={selectingStart ? 'primary' : 'secondary'}
                    size="small"
                    onClick={() => setSelectingStart(true)}
                >
                    Start:{' '}
                    {localFrom
                        ? localFrom.format(use24HourFormat ? DATE_TIME_FORMAT_24H : DATE_TIME_FORMAT_12H)
                        : 'Not set'}
                </LemonButton>
                <LemonButton
                    type={!selectingStart ? 'primary' : 'secondary'}
                    size="small"
                    onClick={() => setSelectingStart(false)}
                >
                    End:{' '}
                    {localTo
                        ? localTo.format(use24HourFormat ? DATE_TIME_FORMAT_24H : DATE_TIME_FORMAT_12H)
                        : 'Not set'}
                </LemonButton>
            </div>
            <div className="p-2">
                <LemonCalendar
                    onDateClick={(date) => {
                        if (date) {
                            const currentValue = selectingStart ? localFrom : localTo
                            const newDate = date
                                .hour(currentValue?.hour() ?? dayjs().hour())
                                .minute(currentValue?.minute() ?? dayjs().minute())

                            if (selectingStart) {
                                setLocalFrom(newDate)
                                // Auto-set end to 1 hour later if not set or if new start is after current end
                                if (!localTo || newDate.isAfter(localTo)) {
                                    setLocalTo(newDate.add(1, 'hour'))
                                }
                            } else {
                                // If end date is before start, swap them
                                if (localFrom && newDate.isBefore(localFrom)) {
                                    setLocalTo(localFrom)
                                    setLocalFrom(newDate)
                                } else {
                                    setLocalTo(newDate)
                                }
                            }
                        }
                    }}
                    leftmostMonth={(selectingStart ? localFrom : localTo)?.startOf('month')}
                    getLemonButtonProps={({ date, props }) => {
                        const currentValue = selectingStart ? localFrom : localTo
                        if (date.isSame(currentValue, 'd')) {
                            return { ...props, status: 'default', type: 'primary' }
                        }
                        return props
                    }}
                    getLemonButtonTimeProps={(timeProps) => {
                        const currentValue = selectingStart ? localFrom : localTo
                        const selected = currentValue
                            ? timeProps.unit === 'h' && use24HourFormat
                                ? String(currentValue.hour())
                                : currentValue.format(timeProps.unit)
                            : null

                        return {
                            active: selected === String(timeProps.value),
                            className: 'rounded-none',
                            'data-attr': `${timeProps.value}-${timeProps.unit}`,
                            onClick: () => {
                                if (currentValue) {
                                    let newDate = currentValue
                                    if (timeProps.unit === 'h') {
                                        if (use24HourFormat) {
                                            newDate = currentValue.hour(Number(timeProps.value))
                                        } else {
                                            const isPM = currentValue.format('a') === 'pm'
                                            newDate = currentValue.hour(
                                                isPM && timeProps.value !== 12
                                                    ? Number(timeProps.value) + 12
                                                    : !isPM && timeProps.value === 12
                                                      ? 0
                                                      : Number(timeProps.value)
                                            )
                                        }
                                    } else if (timeProps.unit === 'm') {
                                        newDate = currentValue.minute(Number(timeProps.value))
                                    } else if (timeProps.unit === 'a') {
                                        const currentHour = currentValue.hour()
                                        if (timeProps.value === 'am' && currentHour >= 12) {
                                            newDate = currentValue.subtract(12, 'hour')
                                        } else if (timeProps.value === 'pm' && currentHour < 12) {
                                            newDate = currentValue.add(12, 'hour')
                                        }
                                    }
                                    if (selectingStart) {
                                        setLocalFrom(newDate)
                                        if (localTo && newDate.isAfter(localTo)) {
                                            setLocalTo(newDate.add(1, 'hour'))
                                        }
                                    } else {
                                        setLocalTo(newDate)
                                        if (localFrom && newDate.isBefore(localFrom)) {
                                            setLocalFrom(newDate.subtract(1, 'hour'))
                                        }
                                    }
                                }
                            },
                        }
                    }}
                    granularity="minute"
                    use24HourFormat={use24HourFormat}
                />
            </div>
            <div
                className={clsx(
                    'flex gap-2 items-center border-t p-2 pt-4',
                    showTimeToggle ? 'justify-between' : 'justify-end'
                )}
                data-attr="lemon-calendar-range-with-time-footer"
            >
                {showTimeToggle && (
                    <LemonSwitch label="Include time?" checked={true} onChange={() => onToggleTime?.(false)} bordered />
                )}
                <div className="flex gap-2">
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" disabled={!localFrom || !localTo} onClick={handleApply}>
                        Apply
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
