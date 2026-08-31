import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { VerificationCodeInput } from './VerificationCodeInput'

type StoryArgs = {
    initialValue?: string
    error?: string | null
    disabled?: boolean
}

function InteractiveCode({ initialValue = '', error = null, disabled = false }: StoryArgs): JSX.Element {
    const [value, setValue] = useState(initialValue)

    return <VerificationCodeInput value={value} onChange={setValue} error={error} disabled={disabled} />
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Authentication/VerificationCodeInput',
    parameters: {
        viewMode: 'story',
    },
    render: (args) => (
        // The verification card is 27rem wide, minus its padding.
        <div className="w-90 p-4">
            <InteractiveCode {...args} />
        </div>
    ),
}
export default meta
type Story = StoryObj<StoryArgs>

export const Empty: Story = {}

export const Filled: Story = { args: { initialValue: '123456' } }

export const Rejected: Story = { args: { error: 'This code is invalid or has expired.' } }

export const Verifying: Story = { args: { initialValue: '123456', disabled: true } }

/** Six slots must also fit where a settings modal or a docked panel is narrow. */
export const Narrow: Story = {
    args: { initialValue: '1234' },
    render: (args) => (
        <div className="w-80 p-4">
            <InteractiveCode {...args} />
        </div>
    ),
}
