import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput, LemonCalendarSelectInputProps } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

type Story = StoryObj<LemonCalendarSelectInputProps>
const meta: Meta<LemonCalendarSelectInputProps> = {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar Select Input',
    component: LemonCalendarSelectInput,
    parameters: {
        mockDate: '2023-01-26 16:30:00',
    },
    tags: ['autodocs'],
    render: (props) => {
        const [value, setValue] = useState<dayjs.Dayjs | null>(dayjs())

        return (
            <div className="w-64">
                <LemonCalendarSelectInput
                    {...props}
                    value={value}
                    onChange={(value) => {
                        setValue(value)
                    }}
                />
            </div>
        )
    },
}
export default meta

export const Default: Story = {
    args: {},
}

export const WithTime: Story = {
    args: { granularity: 'minute' },
}

export const WithTime24Hour: Story = {
    args: { granularity: 'minute', use24HourFormat: true },
}
