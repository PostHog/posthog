import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonCheckbox, LemonCheckboxProps } from './LemonCheckbox'

export default {
    title: 'Lemon UI/Lemon Checkbox',
    component: LemonCheckbox,
} as ComponentMeta<typeof LemonCheckbox>

const Template: ComponentStory<typeof LemonCheckbox> = (props: LemonCheckboxProps) => {
    return <LemonCheckbox {...props} />
}

export const Basic = Template.bind({})
Basic.args = {
    label: 'Check this out',
}

export const Standalone = Template.bind({})
Standalone.args = {}
