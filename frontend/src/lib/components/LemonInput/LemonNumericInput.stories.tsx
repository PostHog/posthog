import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'

import { LemonNumericInput, LemonNumericInputProps } from './LemonNumericInput'
import { IconArrowDropDown, IconFilter } from 'lib/components/icons'
import { LemonButtonWithPopup } from 'lib/components/LemonButton'

export default {
    title: 'Lemon UI/Lemon Numeric Input',
    component: LemonNumericInput,
    argTypes: {
        value: { defaultValue: 'Foo' },
    },
} as ComponentMeta<typeof LemonNumericInput>

const Template: ComponentStory<typeof LemonNumericInput> = (props: LemonNumericInputProps) => {
    const [value, setValue] = useState(props.value)
    return <LemonNumericInput {...props} value={value} onChange={(newValue) => setValue(newValue as number)} />
}

export const Basic = Template.bind({})

export const WithFilterIconAndSideAction = Template.bind({})
WithFilterIconAndSideAction.args = {
    icon: <IconFilter />,
    sideIcon: (
        <LemonButtonWithPopup
            popup={{
                overlay: 'Surprise! 😱',
            }}
            type="tertiary"
            icon={<IconArrowDropDown />}
        />
    ),
}

export const Disabled = Template.bind({})
Disabled.args = { disabled: true }

export const Embedded = Template.bind({})
Embedded.args = { embedded: true }

export const Clearable = Template.bind({})
Clearable.args = { allowClear: true }
