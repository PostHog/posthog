import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { HogQLEditor } from './HogQLEditor'

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

export const HogQLEditor_: Story = Template.bind({})
HogQLEditor_.args = {}

export const NoValue: Story = Template.bind({})
NoValue.args = {
    value: '',
    disableAutoFocus: true,
}

export const NoValuePersonPropertiesDisabled: Story = Template.bind({})
NoValuePersonPropertiesDisabled.args = {
    disablePersonProperties: true,
    value: '',
    disableAutoFocus: true,
}
