import React, { useState } from 'react'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/components/LemonButton'
import { IconClose } from 'lib/components/icons'
import { formatDate, formatDateRange } from 'lib/utils'
import { LemonCalendarRangeInline } from './LemonCalendarRangeInline'

export interface LemonCalendarRangeProps {
    value?: [string, string] | null
    onChange: (date: [string, string]) => void
    months?: number
    onClose?: () => void
}

export function LemonCalendarRange({ value, onChange, onClose, months }: LemonCalendarRangeProps): JSX.Element {
    // Keep a sanitised and cached copy of the selected range
    const [valueStart, valueEnd] = [
        value?.[0] ? dayjs(value[0]).format('YYYY-MM-DD') : null,
        value?.[1] ? dayjs(value[1]).format('YYYY-MM-DD') : null,
    ]
    const [[rangeStart, rangeEnd], setRange] = useState([valueStart, valueEnd])

    return (
        <div className="LemonCalendarRange" data-attr="lemon-calendar-range">
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
                <LemonCalendarRangeInline value={value} onChange={setRange} months={months} />
            </div>
            <div className="flex space-x-2 justify-end items-center border-t p-2 pt-4">
                {rangeStart && rangeEnd && (
                    <div className="flex-1">
                        <span className="text-muted">Selected period:</span>{' '}
                        <span>
                            {rangeStart === rangeEnd
                                ? formatDate(dayjs(rangeStart))
                                : formatDateRange(dayjs(rangeStart), dayjs(rangeEnd))}
                        </span>
                    </div>
                )}
                <>
                    <LemonButton type="secondary" onClick={onClose} data-attr="lemon-calendar-range-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabled={!rangeStart || !rangeEnd}
                        onClick={rangeStart && rangeEnd ? () => onChange([rangeStart, rangeEnd]) : undefined}
                        data-attr="lemon-calendar-range-apply"
                    >
                        Apply
                    </LemonButton>
                </>
            </div>
        </div>
    )
}
