import type { Meta, StoryObj } from '@storybook/react'
import { format, subDays } from 'date-fns'
import { CalendarIcon } from 'lucide-react'
import * as React from 'react'

import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill-primitives'

import { DatePicker } from './date-picker'
import { Day } from './use-calendar'

const meta = {
    title: 'Components/DatePicker',
    component: DatePicker,
    tags: ['autodocs'],
} satisfies Meta<typeof DatePicker>

export default meta
type Story = StoryObj<typeof meta>

const initialValue = subDays(new Date(), 3)

const baseArgs = {
    value: initialValue,
    onApply: () => undefined,
}

export const Default: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<Date>(initialValue)
        return <DatePicker value={value} onApply={setValue} />
    },
}

export const WithTime: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<Date>(initialValue)
        return <DatePicker value={value} onApply={setValue} showTime />
    },
}

export const FixedTime: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<Date>(initialValue)
        return <DatePicker value={value} onApply={setValue} showTime showTimeToggle={false} />
    },
}

export const InPopover: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<Date>(initialValue)
        const [open, setOpen] = React.useState(false)
        return (
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger
                    render={
                        <Button variant="outline" size="sm">
                            <CalendarIcon />
                            {format(value, 'MMM do, yyyy')}
                        </Button>
                    }
                />
                <PopoverContent align="start" className="w-auto p-0">
                    <DatePicker
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

export const MinAndMaxDate: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<Date>(initialValue)
        return (
            <DatePicker
                value={value}
                onApply={setValue}
                minDate={subDays(new Date(), 30)}
                maxDate={subDays(new Date(), 1)}
            />
        )
    },
}

export const EuropeanDateFormat: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<Date>(initialValue)
        return <DatePicker value={value} onApply={setValue} dateFormat="DMY" />
    },
}

export const WeekStartsMonday: Story = {
    args: baseArgs,
    render: () => {
        const [value, setValue] = React.useState<Date>(initialValue)
        return <DatePicker value={value} onApply={setValue} weekStartsOn={Day.MONDAY} />
    },
}
