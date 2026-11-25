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
}

export function TimeRangePicker({ value, onChange, ranges = DEFAULT_QUICK_RANGES }: TimeRangePickerProps): JSX.Element {
    const [open, setOpen] = useState(false)
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger render={<Button size="sm" variant="outline" data-attr="dashboard-v2-time-range" />}>
                <IconCalendar />
                {describeTimeRange(value, ranges)}
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto p-0">
                <DateTimePicker
                    value={toPickerValue(value, ranges)}
                    ranges={pickerRanges(ranges)}
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
