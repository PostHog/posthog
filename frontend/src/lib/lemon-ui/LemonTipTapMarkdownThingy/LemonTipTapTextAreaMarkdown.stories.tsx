import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { JSONContent } from '@tiptap/core'
import { useState } from 'react'

import { LemonTipTapTextAreaMarkdown, LemonTipTapTextAreaMarkdownProps } from './LemonTipTapTextAreaMarkdown'

type Story = StoryObj<typeof LemonTipTapTextAreaMarkdown>
const meta: Meta<typeof LemonTipTapTextAreaMarkdown> = {
    title: 'Lemon UI/Lemon TipTap Text Area Markdown',
    component: LemonTipTapTextAreaMarkdown,
    tags: ['autodocs'],
}

export default meta

const Template: StoryFn<typeof LemonTipTapTextAreaMarkdown> = (props: LemonTipTapTextAreaMarkdownProps) => {
    const [value, setValue] = useState<JSONContent | undefined>(props.initialContent)
    return <LemonTipTapTextAreaMarkdown {...props} content={value} onChange={(newValue) => setValue(newValue)} />
}

export const EmptyLemonTextMarkdown: Story = Template.bind({})
EmptyLemonTextMarkdown.args = { content: undefined }
