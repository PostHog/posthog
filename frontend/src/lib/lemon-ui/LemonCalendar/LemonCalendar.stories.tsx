import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { LemonCalendar, LemonCalendarProps } from './LemonCalendar'

type Story = StoryObj<typeof LemonCalendar>
const meta: Meta<typeof LemonCalendar> = {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar',
    component: LemonCalendar,
    args: {
        onDateClick: (date: dayjs.Dayjs) => {
            // eslint-disable-next-line no-console
            console.log(`Clicked: ${date}`)
        },
    },
    parameters: {
        mockDate: '2023-01-26',
    },
    tags: ['autodocs'],
}
export default meta

const BasicTemplate: StoryFn<typeof LemonCalendar> = (props: LemonCalendarProps) => {
    return <LemonCalendar {...props} />
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}

export const MultipleMonths: Story = BasicTemplate.bind({})
MultipleMonths.args = {
    months: 3,
}

export const CustomStyles: Story = BasicTemplate.bind({})
CustomStyles.args = {
    getLemonButtonProps: ({ date, props }) => {
        return {
            ...props,
            active: date.day() % 2 === 0,
            type: date.date() % 10 === 0 ? 'primary' : undefined,
        }
    },
}

export const MondayFirst: Story = BasicTemplate.bind({})
MondayFirst.args = {
    weekStartDay: 1,
}

export const TuesdayFirst: Story = BasicTemplate.bind({})
TuesdayFirst.args = {
    weekStartDay: 2,
}

export const WednesdayFirst: Story = BasicTemplate.bind({})
WednesdayFirst.args = {
    weekStartDay: 3,
}

export const ThursdayFirst: Story = BasicTemplate.bind({})
ThursdayFirst.args = {
    weekStartDay: 4,
}

export const FridayFirst: Story = BasicTemplate.bind({})
FridayFirst.args = {
    weekStartDay: 5,
}

export const SaturdayFirst: Story = BasicTemplate.bind({})
SaturdayFirst.args = {
    weekStartDay: 6,
}

export const SundayFirst: Story = BasicTemplate.bind({})
SundayFirst.args = {
    weekStartDay: 0,
}

export const Hour: Story = BasicTemplate.bind({})
Hour.args = {
    granularity: 'hour',
}

export const Minute: Story = BasicTemplate.bind({})
Minute.args = {
    granularity: 'minute',
}
