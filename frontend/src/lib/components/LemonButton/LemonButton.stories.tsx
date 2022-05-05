import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonButton, LemonButtonProps } from './LemonButton'
import { IconSync } from '../icons'

export default {
    title: 'Lemon UI/Lemon Button',
    component: LemonButton,
} as ComponentMeta<typeof LemonButton>

const Template: ComponentStory<typeof LemonButton> = (props: LemonButtonProps) => {
    return <LemonButton {...props} />
}

export const Default = Template.bind({})
Default.args = {
    children: 'Click me',
    icon: <IconSync/>
}

export const Small = Template.bind({})
Small.args = {
    children: 'Click me',
    size: "small",
    icon: <IconSync/>
}

export const Large = Template.bind({})
Large.args = {
    children: 'Click me',
    size: "large",
    icon: <IconSync/>
}
