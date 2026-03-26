import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { LemonTextArea, type LemonTextAreaProps } from './LemonTextArea'

type Story = StoryObj<LemonTextAreaProps>
const meta: Meta<LemonTextAreaProps> = {
    title: 'Lemon UI/Lemon Text Area',
    component: LemonTextArea as any,
    args: {
        value: 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.',
    },
    tags: ['autodocs'],
    render: (props) => {
        const [value, setValue] = useState(props.value)
        return <LemonTextArea {...props} value={value} onChange={(newValue) => setValue(newValue)} />
    },
}
export default meta

export const Basic: Story = {
    args: {},
}

export const Disabled: Story = {
    args: { disabled: true },
}

export const WithMaxLength: Story = {
    args: { maxLength: 100, value: '1234567890' },
}

export const WithMaxLengthExceeded: Story = {
    args: { maxLength: 5, value: '1234567890' },
}

export const WithArbitraryAction: Story = {
    args: {
        maxLength: 5,
        value: '1234567890',
        actions: [<LemonButton key="1" icon={<IconTrash />} size="xsmall" />],
    },
}
