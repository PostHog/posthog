import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'

import { LemonSwitch, LemonSwitchProps } from './LemonSwitch'

export default {
    title: 'Lemon UI/Lemon Switch',
    component: LemonSwitch,
    argTypes: {
        label: {
            defaultValue: 'Switch this!',
        },
    },
} as ComponentMeta<typeof LemonSwitch>

const Template: ComponentStory<typeof LemonSwitch> = (props: LemonSwitchProps) => {
    const [isChecked, setIsChecked] = useState(false)
    return <LemonSwitch {...props} checked={isChecked} onChange={setIsChecked} />
}

export const Basic = Template.bind({})
Basic.args = {}

export const Primary = Template.bind({})
Primary.args = { type: 'primary' }

export const Disabled = Template.bind({})
Disabled.args = { disabled: true, label: "Can't switch this" }

export const Standalone = Template.bind({})
Standalone.args = { label: undefined }
