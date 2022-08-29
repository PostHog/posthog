import { LemonCalendar, LemonCalendarProps } from 'lib/components/LemonCalendar/LemonCalendar'
import React, { useEffect, useState } from 'react'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/components/LemonButton'
import { IconClose } from 'lib/components/icons'
import { dateFilterToText } from 'lib/utils'

interface LemonCalendarRangeProps {
    value?: [string | null, string | null]
    onChange: (date: [string | null, string | null]) => void
    months?: number
    getLemonButtonProps?: LemonCalendarProps['getLemonButtonProps']
    onClose?: () => void
}

export function LemonCalendarRange({ value, onChange, onClose, months }: LemonCalendarRangeProps): JSX.Element {
    const [valueStart, valueEnd] = value ?? [null, null]
    const [storedValues, setStoredValues] = useState([valueStart, valueEnd])
    const [storedStart, storedEnd] = storedValues
    const [startMovedLast, setStartMovedLast] = useState(false)
    useEffect(() => {
        if (valueStart !== storedStart) {
            setStartMovedLast(true)
        }
    }, [valueStart, storedStart])
    useEffect(() => {
        if (valueEnd !== storedEnd) {
            setStartMovedLast(false)
        }
    }, [valueEnd, storedEnd])
    const rangeStart = storedStart ? dayjs(storedStart).format('YYYY-MM-DD') : undefined
    const rangeEnd = storedEnd ? dayjs(storedEnd).format('YYYY-MM-DD') : undefined

    return (
        <div className="LemonCalendarRange">
            <div className="flex justify-between border-b p-2 pb-4">
                <h3 className="mb-0">Select a fixed time period</h3>
                {onClose && (
                    <LemonButton
                        icon={<IconClose />}
                        size="small"
                        status="stealth"
                        onClick={onClose}
                        aria-label="close"
                    />
                )}
            </div>
            <div className="p-2">
                <LemonCalendar
                    onClick={(date) => {
                        if (!rangeStart && !rangeEnd) {
                            setStoredValues([date, date])
                        } else if (rangeStart && !rangeEnd) {
                            setStoredValues(date < rangeStart ? [date, rangeStart] : [rangeStart, date])
                        } else if (rangeEnd && !rangeStart) {
                            setStoredValues(date < rangeEnd ? [date, rangeEnd] : [rangeEnd, date])
                        } else if (rangeStart && rangeEnd) {
                            if (date === rangeStart || date === rangeEnd) {
                                setStoredValues([date, date])
                            } else if (date < rangeStart) {
                                setStoredValues([date, rangeEnd])
                            } else if (date > rangeEnd) {
                                setStoredValues([rangeStart, date])
                            } else if (startMovedLast) {
                                setStoredValues([date, rangeEnd])
                            } else {
                                setStoredValues([rangeStart, date])
                            }
                        }
                    }}
                    firstMonth={rangeStart}
                    months={months}
                    getLemonButtonProps={(date, _, defaultProps) => {
                        if (date === rangeStart || date === rangeEnd) {
                            return { ...defaultProps, status: 'primary', type: 'primary' }
                        } else if (rangeStart && rangeEnd && date > rangeStart && date < rangeEnd) {
                            return { ...defaultProps, active: true }
                        }
                        return defaultProps
                    }}
                />
            </div>
            <div className="flex space-x-2 justify-end items-center border-t p-2 pt-4">
                <div className="flex-1">
                    <span className="text-muted">Selected period:</span>{' '}
                    <span>{dateFilterToText(storedStart, storedEnd, '')}</span>
                </div>
                <LemonButton type="secondary" onClick={onClose}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    disabled={!rangeStart || !rangeEnd}
                    onClick={() => onChange([storedStart, storedEnd])}
                >
                    Apply
                </LemonButton>
            </div>
        </div>
    )
}
