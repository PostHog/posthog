import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'

import { LemonInput, LemonInputProps } from './LemonInput'
import { IconArrowDropDown, IconMagnifier } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'

export default {
    title: 'Lemon UI/Input',
    component: LemonInput,
    argTypes: {
        value: { defaultValue: 'Foo' },
    },
} as ComponentMeta<typeof LemonInput>

const Template: ComponentStory<typeof LemonInput> = (props: LemonInputProps) => {
    const [value, setValue] = useState(props.value)
    return <LemonInput {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const Default = Template.bind({})
Default.args = {}

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
