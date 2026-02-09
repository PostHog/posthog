import clsx from 'clsx'
import { useState } from 'react'

import { IconX } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { formatDate, formatDateRange } from 'lib/utils'

import { LemonCalendarRangeInline } from './LemonCalendarRangeInline'

export interface LemonCalendarRangeProps {
    value?: [dayjs.Dayjs, dayjs.Dayjs] | null
    onChange: (range: [dayjs.Dayjs, dayjs.Dayjs]) => void
    months?: number
    onClose?: () => void
    /** Whether to show the "Include time?" toggle */
    showTimeToggle?: boolean
    /** Callback when time toggle is changed */
    onToggleTime?: (includeTime: boolean) => void
}

export function LemonCalendarRange({
    value,
    onChange,
    onClose,
    months,
    showTimeToggle,
    onToggleTime,
}: LemonCalendarRangeProps): JSX.Element {
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
            <div
                className={clsx(
                    'flex deprecated-space-x-2 items-center border-t p-2 pt-4',
                    showTimeToggle ? 'justify-between' : 'justify-end'
                )}
            >
                {showTimeToggle && (
                    <LemonSwitch label="Include time?" checked={false} onChange={() => onToggleTime?.(true)} bordered />
                )}
                {rangeStart && rangeEnd && (
                    <div className="flex-1 text-right">
                        <span className="text-secondary">Selected:</span>{' '}
                        <span>
                            {rangeStart.isSame(rangeEnd, 'd')
                                ? formatDate(rangeStart)
                                : formatDateRange(rangeStart, rangeEnd)}
                        </span>
                    </div>
                )}
                <div className="flex gap-2">
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
                </div>
            </div>
        </div>
    )
}
