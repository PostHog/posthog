import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonCalendar, LemonCalendarProps } from './LemonCalendar'
import { dayjs } from 'lib/dayjs'

export default {
    title: 'Lemon UI/Lemon Calendar/Lemon Calendar',
    component: LemonCalendar,
    argTypes: {
        onClick: {
            defaultValue: (date: string) => {
                console.log(`Clicked: ${date}`)
            },
        },
    },
} as ComponentMeta<typeof LemonCalendar>

const BasicTemplate: ComponentStory<typeof LemonCalendar> = (props: LemonCalendarProps) => {
    return <LemonCalendar {...props} />
}

export const Default = BasicTemplate.bind({})
Default.args = {}

export const MultipleMonths = BasicTemplate.bind({})
MultipleMonths.args = {
    months: 3,
}

export const CustomStyles = BasicTemplate.bind({})
CustomStyles.args = {
    getLemonButtonProps: ({ date, props }) => {
        return {
            ...props,
            active: dayjs(date).day() % 2 === 0,
            status: dayjs(date).date() % 10 === 0 ? 'primary' : 'stealth',
            type: dayjs(date).date() % 10 === 0 ? 'primary' : undefined,
        }
    },
}

export const MondayFirst = BasicTemplate.bind({})
MondayFirst.args = {
    weekStart: 1,
}

export const TuesdayFirst = BasicTemplate.bind({})
TuesdayFirst.args = {
    weekStart: 2,
}

export const WednesdayFirst = BasicTemplate.bind({})
WednesdayFirst.args = {
    weekStart: 3,
}

export const ThursdayFirst = BasicTemplate.bind({})
ThursdayFirst.args = {
    weekStart: 4,
}

export const FridayFirst = BasicTemplate.bind({})
FridayFirst.args = {
    weekStart: 5,
}

export const SaturdayFirst = BasicTemplate.bind({})
SaturdayFirst.args = {
    weekStart: 6,
}

export const SundayFirst = BasicTemplate.bind({})
SundayFirst.args = {
    weekStart: 0,
}
