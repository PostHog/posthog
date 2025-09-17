import { useState } from 'react'

import { IconX } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { formatDate, formatDateRange } from 'lib/utils'

import { LemonCalendarRangeInline } from './LemonCalendarRangeInline'

export interface LemonCalendarRangeProps {
    value?: [dayjs.Dayjs, dayjs.Dayjs] | null
    onChange: (range: [dayjs.Dayjs, dayjs.Dayjs]) => void
    months?: number
    onClose?: () => void
}

export function LemonCalendarRange({ value, onChange, onClose, months }: LemonCalendarRangeProps): JSX.Element {
    // Keep a sanitised and cached copy of the selected range
    const [[rangeStart, rangeEnd], setRange] = useState([
        value?.[0] ? value[0].startOf('day') : null,
        value?.[1] ? value[1].endOf('day') : null,
    ])

    return (
        <div className="LemonCalendarRange" data-attr="lemon-calendar-range">
            <div className="flex justify-between border-b p-2 pb-4">
                <h3 className="text-base mb-0">Select a date range</h3>
                {onClose && (
                    <LemonButton icon={<IconX />} size="small" noPadding onClick={onClose} aria-label="close" />
                )}
            </div>
            <div className="p-2">
                <LemonCalendarRangeInline value={value} onChange={setRange} months={months} />
            </div>
            <div className="flex deprecated-space-x-2 justify-end items-center border-t p-2 pt-4">
                {rangeStart && rangeEnd && (
                    <div className="flex-1">
                        <span className="text-secondary">Selected period:</span>{' '}
                        <span>
                            {rangeStart.isSame(rangeEnd, 'd')
                                ? formatDate(rangeStart)
                                : formatDateRange(rangeStart, rangeEnd)}
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
