import type { Meta, StoryObj } from '@storybook/react'
import { subDays } from 'date-fns'
import { Clock } from 'lucide-react'
import * as React from 'react'

import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill-primitives'

import { DateTimePicker, type DateTimeValue } from './date-time-picker'
import { quickRanges } from './date-time-ranges'
import { Day } from './use-calendar'

const meta = {
    title: 'Components/DateTimePicker',
    component: DateTimePicker,
    tags: ['autodocs'],
} satisfies Meta<typeof DateTimePicker>

export default meta
type Story = StoryObj<typeof meta>

const initialValue: DateTimeValue = {
    start: subDays(new Date(), 7),
    end: new Date(),
    range: quickRanges.find((r) => r.name === 'Last 7 days')!,
}

const baseArgs = {
    value: initialValue,
    onApply: () => undefined,
}

export const Default: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        return <DateTimePicker value={value} onApply={setValue} />
    },
}

export const InPopover: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        const [open, setOpen] = React.useState(false)
        return (
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger
                    render={
                        <Button variant="outline" size="sm">
                            <Clock />
                            {value.range.name}
                        </Button>
                    }
                />
                <PopoverContent align="start" className="w-auto p-0">
                    <DateTimePicker
                        value={value}
                        onApply={(next) => {
                            setValue(next)
                            setOpen(false)
                        }}
                        onCancel={() => setOpen(false)}
                    />
                </PopoverContent>
            </Popover>
        )
    },
}

export const CustomMaxDate: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>({
            start: subDays(new Date(), 14),
            end: subDays(new Date(), 7),
            range: quickRanges[0],
        })
        return <DateTimePicker value={value} onApply={setValue} maxDate={subDays(new Date(), 1)} />
    },
}

export const EuropeanDateFormat: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        return <DateTimePicker value={value} onApply={setValue} dateFormat="DMY" />
    },
}

export const ISODateFormat: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        return <DateTimePicker value={value} onApply={setValue} dateFormat="YMD" />
    },
}

export const WithSettingsLink: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        return (
            <DateTimePicker
                value={value}
                onApply={setValue}
                onDateTimeSettings={() => alert('Open date & time settings')}
            />
        )
    },
}

export const WeekStartsMonday: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        return <DateTimePicker value={value} onApply={setValue} weekStartsOn={Day.THURSDAY} />
    },
}

export const NarrowContainer: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<DateTimeValue>(initialValue)
        return <DateTimePicker value={value} onApply={setValue} compact />
    },
}
