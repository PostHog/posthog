import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { type LemonTextAreaProps } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import {
    LemonTextAreaMarkdown,
    LemonTextAreaMarkdown as _LemonTextMarkdown,
} from 'lib/lemon-ui/LemonTextArea/LemonTextAreaMarkdown'

type Story = StoryObj<LemonTextAreaProps>
const meta: Meta<LemonTextAreaProps> = {
    title: 'Lemon UI/Lemon Text Area Markdown',
    component: LemonTextAreaMarkdown as any,
    args: {
        value: 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.',
    },
    tags: ['autodocs'],
    render: (props) => {
        const [value, setValue] = useState(props.value)
        return <_LemonTextMarkdown {...props} value={value} onChange={(newValue) => setValue(newValue)} />
    },
}

export default meta

export const EmptyLemonTextMarkdown: Story = {
    args: { value: '' },
}

export const LemonTextMarkdownWithText: Story = {
    args: { value: '# Title\n\n**bold** _italic_' },
}

export const LemonTextMarkdownWithMaxLength: Story = {
    args: { value: '# Title\n\n**bold** _italic_', maxLength: 12 },
}
