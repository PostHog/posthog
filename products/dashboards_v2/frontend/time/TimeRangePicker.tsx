import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import { Button, DateTimePicker, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import type { TimeRange } from '../dashboard/dashboardTypes'
import {
    DEFAULT_QUICK_RANGES,
    type QuickRange,
    describeTimeRange,
    fromPickerValue,
    pickerRanges,
    toPickerValue,
} from './timeRanges'

export interface TimeRangePickerProps {
    value: TimeRange
    onChange: (time: TimeRange) => void
    ranges?: QuickRange[]
    /** The project's timezone, which a saved time without an offset is in. Left out, it is the browser's. */
    timezone?: string
}

export function TimeRangePicker({
    value,
    onChange,
    ranges = DEFAULT_QUICK_RANGES,
    timezone,
}: TimeRangePickerProps): JSX.Element {
    const [open, setOpen] = useState(false)
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger render={<Button size="sm" variant="outline" data-attr="dashboard-v2-time-range" />}>
                <IconCalendar />
                <span>{describeTimeRange(value, ranges, timezone)}</span>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto p-0">
                <DateTimePicker
                    value={toPickerValue(value, ranges, timezone)}
                    ranges={pickerRanges(ranges, timezone)}
                    showTime={false}
                    onApply={(next) => {
                        onChange(fromPickerValue(next, ranges))
                        setOpen(false)
                    }}
                    onCancel={() => setOpen(false)}
                />
            </PopoverContent>
        </Popover>
    )
}
