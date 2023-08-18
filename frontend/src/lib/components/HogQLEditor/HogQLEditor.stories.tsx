import { StoryFn, Meta, StoryObj } from '@storybook/react'
import { HogQLEditor } from './HogQLEditor'
import { useState } from 'react'

type Story = StoryObj<typeof HogQLEditor>
const meta: Meta<typeof HogQLEditor> = {
    title: 'Components/HogQLEditor',
    component: HogQLEditor,
}
export default meta

const Template: StoryFn<typeof HogQLEditor> = (props): JSX.Element => {
    const [value, onChange] = useState(props.value ?? "countIf(properties.$browser = 'Chrome')")
    return <HogQLEditor {...props} value={value} onChange={onChange} />
}

export const HogQLEditor_: Story = {
    render: Template,
    args: {},
}

export const NoValue: Story = {
    render: Template,

    args: {
        value: '',
        disableAutoFocus: true,
    },
}

export const NoValuePersonPropertiesDisabled: Story = {
    render: Template,

    args: {
        disablePersonProperties: true,
        value: '',
        disableAutoFocus: true,
    },
}
