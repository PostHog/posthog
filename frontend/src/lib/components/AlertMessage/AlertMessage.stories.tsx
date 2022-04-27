import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { AlertMessage, AlertMessageProps } from './AlertMessage'

export default {
    title: 'Lemon UI/Alert Message',
    component: AlertMessage,
} as ComponentMeta<typeof AlertMessage>

const Template: ComponentStory<typeof AlertMessage> = (props: AlertMessageProps) => {
    return <AlertMessage {...props} />
}

export const Info = Template.bind({})
Info.args = { type: 'info', children: 'PSA: Every dish can be improved by adding more garlic.' }

export const Warning = Template.bind({})
Warning.args = { type: 'warning', children: 'This spacecraft is about to explode. Please evacuate immediately.' }
