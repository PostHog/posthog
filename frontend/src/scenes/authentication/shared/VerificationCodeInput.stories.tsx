import type { Meta, StoryFn } from '@storybook/react'
import { useState } from 'react'

import { VerificationCodeInput } from './VerificationCodeInput'

type StoryArgs = {
    initialValue: string
    error: string | null
    disabled: boolean
    width: number
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Authentication/VerificationCodeInput',
    parameters: {
        viewMode: 'story',
    },
    argTypes: {
        initialValue: { control: 'text', name: 'Value' },
        error: { control: 'text', name: 'Error' },
        disabled: { control: 'boolean', name: 'Disabled' },
        width: { control: 'number', name: 'Container width' },
    },
    args: {
        initialValue: '',
        error: null,
        disabled: false,
        // The verification card is 27rem wide, minus its padding.
        width: 360,
    },
}
export default meta

const Template: StoryFn<StoryArgs> = ({ initialValue, error, disabled, width }) => {
    const [value, setValue] = useState(initialValue)

    return (
        <div className="p-4" style={{ width }}>
            <VerificationCodeInput value={value} onChange={setValue} error={error} disabled={disabled} />
        </div>
    )
}

export const Empty: StoryFn<StoryArgs> = Template.bind({})

export const Filled: StoryFn<StoryArgs> = Template.bind({})
Filled.args = { initialValue: '123456' }

export const Rejected: StoryFn<StoryArgs> = Template.bind({})
Rejected.args = { error: 'This code is invalid or has expired.' }

export const Verifying: StoryFn<StoryArgs> = Template.bind({})
Verifying.args = { initialValue: '123456', disabled: true }

/** Six slots still have to fit where a settings modal or a docked panel is narrow. */
export const Narrow: StoryFn<StoryArgs> = Template.bind({})
Narrow.args = { initialValue: '1234', width: 320 }
