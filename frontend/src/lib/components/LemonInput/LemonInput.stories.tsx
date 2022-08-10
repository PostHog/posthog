import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'

import { LemonInput } from './LemonInput'
import { IconArrowDropDown, IconCalendar } from 'lib/components/icons'
import { LemonButtonWithPopup } from 'lib/components/LemonButton'

export default {
    title: 'Lemon UI/Lemon Input',
    component: LemonInput,
    argTypes: {
        value: { defaultValue: 'Foo' },
    },
} as ComponentMeta<typeof LemonInput>

const Template: ComponentStory<typeof LemonInput> = (props) => {
    const [value, setValue] = useState(props.value)
    // @ts-expect-error – union variant inference around the `type` prop doesn't work here as `type` comes from above
    return <LemonInput {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const Basic = Template.bind({})

export const WithIconAndSideAction = Template.bind({})
WithIconAndSideAction.args = {
    icon: <IconCalendar />,
    sideIcon: (
        <LemonButtonWithPopup
            noPadding
            popup={{
                overlay: 'Surprise! 😱',
            }}
            type="tertiary"
            icon={<IconArrowDropDown />}
        />
    ),
}

export const Search = Template.bind({})
Search.args = { type: 'search', placeholder: 'Search your soul' }

export const Disabled = Template.bind({})
Disabled.args = { disabled: true }

export const Embedded = Template.bind({})
Embedded.args = { embedded: true }

export const Clearable = Template.bind({})
Clearable.args = { allowClear: true }

export const Numeric = Template.bind({})
Numeric.args = { type: 'number', min: 0, step: 1, value: 3 }
