import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { LemonCalendar, LemonCalendarProps } from './LemonCalendar'
import { dayjs } from 'lib/dayjs'

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

export const Default: Story = {
    render: BasicTemplate,
    args: {},
}

export const MultipleMonths: Story = {
    render: BasicTemplate,

    args: {
        months: 3,
    },
}

export const CustomStyles: Story = {
    render: BasicTemplate,

    args: {
        getLemonButtonProps: ({ date, props }) => {
            return {
                ...props,
                active: date.day() % 2 === 0,
                status: date.date() % 10 === 0 ? 'primary' : 'stealth',
                type: date.date() % 10 === 0 ? 'primary' : undefined,
            }
        },
    },
}

export const MondayFirst: Story = {
    render: BasicTemplate,

    args: {
        weekStart: 1,
    },
}

export const TuesdayFirst: Story = {
    render: BasicTemplate,

    args: {
        weekStart: 2,
    },
}

export const WednesdayFirst: Story = {
    render: BasicTemplate,

    args: {
        weekStart: 3,
    },
}

export const ThursdayFirst: Story = {
    render: BasicTemplate,

    args: {
        weekStart: 4,
    },
}

export const FridayFirst: Story = {
    render: BasicTemplate,

    args: {
        weekStart: 5,
    },
}

export const SaturdayFirst: Story = {
    render: BasicTemplate,

    args: {
        weekStart: 6,
    },
}

export const SundayFirst: Story = {
    render: BasicTemplate,

    args: {
        weekStart: 0,
    },
}
