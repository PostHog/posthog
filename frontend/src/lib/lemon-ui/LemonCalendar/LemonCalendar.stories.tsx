import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { LemonCalendar, LemonCalendarProps } from './LemonCalendar'
import { dayjs } from 'lib/dayjs'

type Story = StoryObj<typeof LemonCalendar>
const meta: Meta<typeof LemonCalendar> = {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar',
    component: LemonCalendar,
    argTypes: {
        onDateClick: {
            defaultValue: (date: dayjs.Dayjs) => {
                // eslint-disable-next-line no-console
                console.log(`Clicked: ${date}`)
            },
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
            status: date.date() % 10 === 0 ? 'primary' : 'stealth',
            type: date.date() % 10 === 0 ? 'primary' : undefined,
        }
    },
}

export const MondayFirst: Story = BasicTemplate.bind({})
MondayFirst.args = {
    weekStart: 1,
}

export const TuesdayFirst: Story = BasicTemplate.bind({})
TuesdayFirst.args = {
    weekStart: 2,
}

export const WednesdayFirst: Story = BasicTemplate.bind({})
WednesdayFirst.args = {
    weekStart: 3,
}

export const ThursdayFirst: Story = BasicTemplate.bind({})
ThursdayFirst.args = {
    weekStart: 4,
}

export const FridayFirst: Story = BasicTemplate.bind({})
FridayFirst.args = {
    weekStart: 5,
}

export const SaturdayFirst: Story = BasicTemplate.bind({})
SaturdayFirst.args = {
    weekStart: 6,
}

export const SundayFirst: Story = BasicTemplate.bind({})
SundayFirst.args = {
    weekStart: 0,
}
