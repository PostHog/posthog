import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'

import { LemonTextArea, LemonTextAreaProps } from './LemonTextArea'
import { IconArrowDropDown, IconMagnifier } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'

export default {
    title: 'Lemon UI/Lemon Text Area',
    component: LemonTextArea,
    argTypes: {
        value: {
            defaultValue:
                'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.',
        },
    },
} as ComponentMeta<typeof LemonTextArea>

const Template: ComponentStory<typeof LemonTextArea> = (props: LemonTextAreaProps) => {
    const [value, setValue] = useState(props.value)
    return <LemonTextArea {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const Basic = Template.bind({})
Basic.args = {}

export const Icons = Template.bind({})
Icons.args = {
    icon: <IconMagnifier style={{ fontSize: 18, color: 'var(--text-muted)' }} />,
    sideIcon: <LemonButton type="tertiary" icon={<IconArrowDropDown style={{ color: 'var(--text-muted)' }} />} />,
}

export const Disabled = Template.bind({})
Disabled.args = { disabled: true }

export const Embedded = Template.bind({})
Embedded.args = { embedded: true }

export const Clearable = Template.bind({})
Clearable.args = { allowClear: true }
