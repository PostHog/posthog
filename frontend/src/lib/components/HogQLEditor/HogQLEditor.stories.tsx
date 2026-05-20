import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { HogQLEditor, HogQLEditorProps } from './HogQLEditor'

type Story = StoryObj<HogQLEditorProps>
const meta: Meta<HogQLEditorProps> = {
    title: 'Components/HogQLEditor',
    component: HogQLEditor,
    render: (props) => {
        const [value, onChange] = useState(props.value ?? "countIf(properties.$browser = 'Chrome')")
        return <HogQLEditor {...props} value={value} onChange={onChange} />
    },
}
export default meta

export const HogQLEditor_: Story = {
    args: {},
}

export const NoValue: Story = {
    args: {
        value: '',
        disableAutoFocus: true,
    },
}

export const NoValuePersonPropertiesDisabled: Story = {
    args: {
        disablePersonProperties: true,
        value: '',
        disableAutoFocus: true,
    },
}
