import type { Meta, StoryObj } from '@storybook/react'

import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'

type Story = StoryObj<typeof meta>
const meta: Meta<typeof EmojiPickerPopover> = {
    title: 'Lemon UI/Emoji Picker Popover',
    component: EmojiPickerPopover,
    tags: ['autodocs'],
    parameters: {
        docs: {
            description: {
                component: 'A component that opens a popover emoji picker.',
            },
        },
    },
    argTypes: {
        onSelect: {
            description: 'The function to run when a user chooses an emoji',
        },
        defaultOpen: {
            description: 'Whether to start with the popover open - defaults to false',
        },
    },
    render: (props) => {
        return (
            <div className="w-[325px] h-[370px] border rounded">
                <EmojiPickerPopover {...props} />
            </div>
        )
    },
}
export default meta

export const Default: Story = {
    args: {},
}

export const Open: Story = {
    args: {
        defaultOpen: true,
    },
}
