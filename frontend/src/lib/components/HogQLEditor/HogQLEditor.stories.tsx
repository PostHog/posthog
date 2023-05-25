import { ComponentStory, Meta } from '@storybook/react'
import { HogQLEditor } from './HogQLEditor'
import { useState } from 'react'

export default {
    title: 'Components/HogQLEditor',
    component: HogQLEditor,
} as Meta<typeof HogQLEditor>

const Template: ComponentStory<typeof HogQLEditor> = (props): JSX.Element => {
    const [value, onChange] = useState(props.value ?? "countIf(properties.$browser = 'Chrome')")
    return <HogQLEditor {...props} value={value} onChange={onChange} />
}

export const HogQLEditor_ = Template.bind({})
HogQLEditor_.args = {}

export const NoValue = Template.bind({})
NoValue.args = {
    value: '',
    disableAutoFocus: true,
}

export const NoValuePersonPropertiesDisabled = Template.bind({})
NoValuePersonPropertiesDisabled.args = {
    disablePersonProperties: true,
    value: '',
    disableAutoFocus: true,
}
