import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonCalendar, LemonCalendarProps } from './LemonCalendar'

export default {
    title: 'Lemon UI/Lemon Calendar',
    component: LemonCalendar,
    argTypes: {
        children: {
            defaultValue: 'Tasty snacks',
        },
    },
} as ComponentMeta<typeof LemonCalendar>

const BasicTemplate: ComponentStory<typeof LemonCalendar> = (props: LemonCalendarProps) => {
    return <LemonCalendar {...props} />
}

export const Default = BasicTemplate.bind({})
Default.args = {
    onClick: (date) => {
        console.log(`Clicked: ${date}`)
    },
}
