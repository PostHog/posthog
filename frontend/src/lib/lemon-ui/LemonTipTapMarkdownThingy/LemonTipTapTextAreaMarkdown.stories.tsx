import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonTextAreaProps } from '../LemonTextArea'
import { LemonTipTapTextAreaMarkdown } from 'lib/lemon-ui/LemonTipTapMarkdownThingy/LemonTipTapTextAreaMarkdown'

type Story = StoryObj<typeof LemonTipTapTextAreaMarkdown>
const meta: Meta<typeof LemonTipTapTextAreaMarkdown> = {
    title: 'Lemon UI/Lemon TipTap Text Area Markdown',
    component: LemonTipTapTextAreaMarkdown,
    args: {
        value: 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.',
    },
    tags: ['autodocs'],
}

export default meta

const Template: StoryFn<typeof LemonTipTapTextAreaMarkdown> = (props: LemonTextAreaProps) => {
    const [value, setValue] = useState(props.value)
    return <LemonTipTapTextAreaMarkdown {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const EmptyLemonTextMarkdown: Story = Template.bind({})
EmptyLemonTextMarkdown.args = { value: '' }

export const LemonTextMarkdownWithText: Story = Template.bind({})
LemonTextMarkdownWithText.args = { value: '# Title\n\n**bold** _italic_' }

export const LemonTextMarkdownWithMaxLength: Story = Template.bind({})
LemonTextMarkdownWithMaxLength.args = { value: '# Title\n\n**bold** _italic_', maxLength: 12 }
