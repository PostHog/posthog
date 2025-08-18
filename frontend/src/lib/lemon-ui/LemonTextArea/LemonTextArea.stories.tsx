import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { LemonTextArea, LemonTextAreaProps } from './LemonTextArea'

type Story = StoryObj<typeof LemonTextArea>
const meta: Meta<typeof LemonTextArea> = {
    title: 'Lemon UI/Lemon Text Area',
    component: LemonTextArea,
    args: {
        value: 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.',
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonTextArea> = (props: LemonTextAreaProps) => {
    const [value, setValue] = useState(props.value)
    return <LemonTextArea {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const Basic: Story = Template.bind({})
Basic.args = {}

export const Disabled: Story = Template.bind({})
Disabled.args = { disabled: true }

export const WithMaxLength: Story = Template.bind({})
WithMaxLength.args = { maxLength: 100, value: '1234567890' }

export const WithMaxLengthExceeded: Story = Template.bind({})
WithMaxLengthExceeded.args = { maxLength: 5, value: '1234567890' }

export const WithArbitraryAction: Story = Template.bind({})
WithArbitraryAction.args = {
    maxLength: 5,
    value: '1234567890',
    actions: [<LemonButton key="1" icon={<IconTrash />} size="xsmall" />],
}
