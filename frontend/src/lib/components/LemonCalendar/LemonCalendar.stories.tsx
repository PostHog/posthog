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
