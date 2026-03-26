import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { LemonCalendar, LemonCalendarProps } from './LemonCalendar'

type Story = StoryObj<LemonCalendarProps>
const meta: Meta<LemonCalendarProps> = {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar',
    component: LemonCalendar as any,
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

export const Default: Story = { args: {} }

export const MultipleMonths: Story = { args: { months: 3 } }

export const CustomStyles: Story = {
    args: {
        getLemonButtonProps: ({ date, props }) => {
            return {
                ...props,
                active: date.day() % 2 === 0,
                type: date.date() % 10 === 0 ? 'primary' : undefined,
            }
        },
    },
}

export const MondayFirst: Story = { args: { weekStartDay: 1 } }

export const TuesdayFirst: Story = { args: { weekStartDay: 2 } }

export const WednesdayFirst: Story = { args: { weekStartDay: 3 } }

export const ThursdayFirst: Story = { args: { weekStartDay: 4 } }

export const FridayFirst: Story = { args: { weekStartDay: 5 } }

export const SaturdayFirst: Story = { args: { weekStartDay: 6 } }

export const SundayFirst: Story = { args: { weekStartDay: 0 } }

export const Hour: Story = { args: { granularity: 'hour' } }

export const Minute: Story = { args: { granularity: 'minute' } }

export const Minute24Hour: Story = { args: { granularity: 'minute', use24HourFormat: true } }
