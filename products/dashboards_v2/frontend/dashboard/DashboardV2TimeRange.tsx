import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import { Button, DateTimePicker, type DateTimeValue, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { pickerValueToTimeRange, timeRangeLabel, timeRangeToPickerValue } from './timeRange'

interface DashboardV2TimeRangeProps {
    from: string
    to: string
    onChange: (from: string, to: string) => void
}

export function DashboardV2TimeRange({ from, to, onChange }: DashboardV2TimeRangeProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const now = new Date()

    const handleApply = (next: DateTimeValue): void => {
        const range = pickerValueToTimeRange(next)
        onChange(range.from, range.to)
        setOpen(false)
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
                render={
                    <Button variant="outline" data-attr="dashboard-v2-time-range">
                        <IconCalendar />
                        <span translate="no">{timeRangeLabel(from, to, now)}</span>
                    </Button>
                }
            />
            <PopoverContent align="end" className="w-auto p-0">
                <DateTimePicker
                    value={timeRangeToPickerValue(from, to, now)}
                    onApply={handleApply}
                    onCancel={() => setOpen(false)}
                />
            </PopoverContent>
        </Popover>
    )
}
