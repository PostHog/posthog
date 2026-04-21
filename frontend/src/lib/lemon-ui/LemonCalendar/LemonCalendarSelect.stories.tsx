import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCalendarSelect, LemonCalendarSelectProps } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { formatDate } from 'lib/utils'

type Story = StoryObj<LemonCalendarSelectProps>
const meta: Meta<LemonCalendarSelectProps> = {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar Select',
    component: LemonCalendarSelect,
    parameters: {
        mockDate: '2023-01-26',
    },
    tags: ['autodocs'],
    render: (props) => {
        const [value, setValue] = useState(dayjs().subtract(10, 'day'))
        const [visible, setVisible] = useState(true)
        const [granularity, setGranularity] = useState<LemonCalendarSelectProps['granularity']>(props.granularity)

        return (
            <div className="pb-[30rem]">
                <Popover
                    actionable
                    overlay={
                        <LemonCalendarSelect
                            {...props}
                            value={value}
                            onChange={(value) => {
                                setValue(value)
                                setVisible(false)
                            }}
                            showTimeToggle={props.showTimeToggle}
                            onToggleTime={() => setGranularity(granularity === 'minute' ? 'day' : 'minute')}
                            granularity={granularity}
                            onClose={() => setVisible(false)}
                        />
                    }
                    visible={visible}
                    onClickOutside={() => setVisible(false)}
                >
                    <LemonButton type="secondary" onClick={() => setVisible(!visible)}>
                        {formatDate(value)}
                    </LemonButton>
                </Popover>
            </div>
        )
    },
}
export default meta

export const Default: Story = { args: { granularity: 'day' } }

export const Upcoming: Story = { args: { selectionPeriod: 'upcoming' } }

export const UpcomingWithLimit: Story = {
    args: { selectionPeriod: 'upcoming', selectionPeriodLimit: dayjs().add(1, 'day') },
}

export const Past: Story = { args: { selectionPeriod: 'past' } }

export const PastWithLimit: Story = {
    args: { selectionPeriod: 'past', selectionPeriodLimit: dayjs().subtract(1, 'day') },
}

export const Hour: Story = { args: { granularity: 'hour' } }

export const Minute: Story = { args: { granularity: 'minute' } }

export const WithTimeToggle: Story = { args: { showTimeToggle: true } }

export const WithTimeToggleAndMultipleMonths: Story = { args: { showTimeToggle: true, months: 3 } }

export const Minute24Hour: Story = { args: { granularity: 'minute', use24HourFormat: true } }
