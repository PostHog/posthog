import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'

type Story = StoryObj<typeof EmojiPickerPopover>
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
}
export default meta

const BasicTemplate: StoryFn<typeof EmojiPickerPopover> = (props) => {
    return (
        <div className="w-[325px] h-[370px] border rounded">
            <EmojiPickerPopover {...props} />
        </div>
    )
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}

export const Open: Story = BasicTemplate.bind({})
Open.args = {
    defaultOpen: true,
}
