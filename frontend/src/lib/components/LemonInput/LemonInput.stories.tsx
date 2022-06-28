import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'

import { LemonInput, LemonInputProps } from './LemonInput'
import { IconArrowDropDown, IconMagnifier } from 'lib/components/icons'
import { LemonButtonWithPopup } from 'lib/components/LemonButton'

export default {
    title: 'Lemon UI/Lemon Input',
    component: LemonInput,
    argTypes: {
        value: { defaultValue: 'Foo' },
    },
} as ComponentMeta<typeof LemonInput>

const Template: ComponentStory<typeof LemonInput> = (props: LemonInputProps) => {
    const [value, setValue] = useState(props.value)
    return <LemonInput {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const Basic = Template.bind({})

export const WithSearchIconAndSideAction = Template.bind({})
WithSearchIconAndSideAction.args = {
    icon: <IconMagnifier />,
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

export const Numeric = Template.bind({})
Numeric.args = { type: 'number', min: 0, step: 1 }
