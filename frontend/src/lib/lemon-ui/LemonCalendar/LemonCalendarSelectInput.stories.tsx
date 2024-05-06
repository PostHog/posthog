import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput, LemonCalendarSelectInputProps } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { useState } from 'react'

type Story = StoryObj<typeof LemonCalendarSelectInput>
const meta: Meta<typeof LemonCalendarSelectInput> = {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar Select',
    component: LemonCalendarSelectInput,
    parameters: {
        mockDate: '2023-01-26 16:30:00',
    },
    tags: ['autodocs'],
}
export default meta

const BasicTemplate: StoryFn<typeof LemonCalendarSelectInput> = (props: LemonCalendarSelectInputProps) => {
    const [value, setValue] = useState<dayjs.Dayjs | null>(dayjs())

    return (
        <div className="w-64">
            <LemonCalendarSelectInput
                {...props}
                value={value}
                onChange={(value) => {
                    setValue(value)
                }}
                showTime
            />
        </div>
    )
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}

export const Controlled: Story = BasicTemplate.bind({})
Controlled.args = { visible: true }

export const Upcoming: Story = BasicTemplate.bind({})
Upcoming.args = { visible: true, selectionPeriod: 'upcoming' }

export const Past: Story = BasicTemplate.bind({})
Past.args = { visible: true, selectionPeriod: 'past' }
