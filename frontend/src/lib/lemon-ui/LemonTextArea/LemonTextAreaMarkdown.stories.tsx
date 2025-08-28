import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import {
    LemonTextAreaMarkdown,
    LemonTextAreaMarkdown as _LemonTextMarkdown,
} from 'lib/lemon-ui/LemonTextArea/LemonTextAreaMarkdown'

import { LemonTextAreaProps } from './LemonTextArea'

type Story = StoryObj<typeof LemonTextAreaMarkdown>
const meta: Meta<typeof LemonTextAreaMarkdown> = {
    title: 'Lemon UI/Lemon Text Area Markdown',
    component: LemonTextAreaMarkdown,
    args: {
        value: 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.',
    },
    tags: ['autodocs'],
}

export default meta

const Template: StoryFn<typeof LemonTextAreaMarkdown> = (props: LemonTextAreaProps) => {
    const [value, setValue] = useState(props.value)
    return <_LemonTextMarkdown {...props} value={value} onChange={(newValue) => setValue(newValue)} />
}

export const EmptyLemonTextMarkdown: Story = Template.bind({})
EmptyLemonTextMarkdown.args = { value: '' }

export const LemonTextMarkdownWithText: Story = Template.bind({})
LemonTextMarkdownWithText.args = { value: '# Title\n\n**bold** _italic_' }

export const LemonTextMarkdownWithMaxLength: Story = Template.bind({})
LemonTextMarkdownWithMaxLength.args = { value: '# Title\n\n**bold** _italic_', maxLength: 12 }
