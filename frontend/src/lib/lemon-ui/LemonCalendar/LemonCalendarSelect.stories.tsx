import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCalendarSelect, LemonCalendarSelectProps } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { formatDate } from 'lib/utils'

type Story = StoryObj<typeof LemonCalendarSelect>
const meta: Meta<typeof LemonCalendarSelect> = {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar Select',
    component: LemonCalendarSelect,
    parameters: {
        mockDate: '2023-01-26',
    },
    tags: ['autodocs'],
}
export default meta

const BasicTemplate: StoryFn<typeof LemonCalendarSelect> = (props: LemonCalendarSelectProps) => {
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
}

export const Default: Story = BasicTemplate.bind({})
Default.args = { granularity: 'day' }

export const Upcoming: Story = BasicTemplate.bind({})
Upcoming.args = { selectionPeriod: 'upcoming' }

export const UpcomingWithLimit: Story = BasicTemplate.bind({})
UpcomingWithLimit.args = { selectionPeriod: 'upcoming', selectionPeriodLimit: dayjs().add(1, 'day') }

export const Past: Story = BasicTemplate.bind({})
Past.args = { selectionPeriod: 'past' }

export const PastWithLimit: Story = BasicTemplate.bind({})
PastWithLimit.args = { selectionPeriod: 'past', selectionPeriodLimit: dayjs().subtract(1, 'day') }

export const Hour: Story = BasicTemplate.bind({})
Hour.args = { granularity: 'hour' }

export const Minute: Story = BasicTemplate.bind({})
Minute.args = { granularity: 'minute' }

export const WithTimeToggle: Story = BasicTemplate.bind({})
WithTimeToggle.args = { showTimeToggle: true }

export const WithTimeToggleAndMultipleMonths: Story = BasicTemplate.bind({})
WithTimeToggleAndMultipleMonths.args = { showTimeToggle: true, months: 3 }
