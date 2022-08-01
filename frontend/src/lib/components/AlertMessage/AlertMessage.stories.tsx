import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { AlertMessage, AlertMessageProps } from './AlertMessage'

export default {
    title: 'Lemon UI/Alert Message',
    component: AlertMessage,
    // See https://github.com/storybookjs/addon-smart-knobs/issues/63#issuecomment-995798227
    parameters: { actions: { argTypesRegex: null } },
} as ComponentMeta<typeof AlertMessage>

const Template: ComponentStory<typeof AlertMessage> = (props: AlertMessageProps) => {
    return <AlertMessage {...props} />
}

export const Info = Template.bind({})
Info.args = { type: 'info', children: 'PSA: Every dish can be improved by adding more garlic.' }

export const Warning = Template.bind({})
Warning.args = { type: 'warning', children: 'This spacecraft is about to explode. Please evacuate immediately.' }

export const Error = Template.bind({})
Error.args = { type: 'error', children: 'This spacecraft has exploded. Too late...' }

export const Closable = Template.bind({})
Closable.args = {
    type: 'info',
    children: 'This is a one-time message. Acknowledge it and move on with your life.',
    onClose: () => alert('👋'),
}
