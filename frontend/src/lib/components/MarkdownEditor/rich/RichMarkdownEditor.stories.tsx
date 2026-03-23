import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { Placeholder } from '@tiptap/extension-placeholder'
import { useState } from 'react'

import {
    markdownToTextCardDoc,
    textCardDocToMarkdown,
    TEXT_CARD_MARKDOWN_EXTENSIONS,
} from 'lib/components/Cards/TextCard/textCardMarkdown'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { RichMarkdownEditor } from './RichMarkdownEditor'

/** Same stack as dashboard text cards: markdown round-trip + placeholder. */
const TEXT_CARD_LIKE_EXTENSIONS = [
    ...TEXT_CARD_MARKDOWN_EXTENSIONS,
    Placeholder.configure({ placeholder: 'Write here. Use the toolbar for formatting…' }),
]

const storyDefaults = {
    extensions: TEXT_CARD_LIKE_EXTENSIONS,
    markdownToDoc: markdownToTextCardDoc,
    docToMarkdown: textCardDocToMarkdown,
    renderPreview: (markdown: string): JSX.Element => <LemonMarkdown>{markdown}</LemonMarkdown>,
    dataAttr: 'story-rich-markdown-editor',
}

type Story = StoryObj<typeof RichMarkdownEditor>

const meta: Meta<typeof RichMarkdownEditor> = {
    title: 'Components/Markdown editor/Rich',
    component: RichMarkdownEditor,
    tags: ['autodocs'],
}

export default meta

const Template: StoryFn<typeof RichMarkdownEditor> = (props) => {
    const [value, setValue] = useState(props.value ?? '')
    return <RichMarkdownEditor {...storyDefaults} {...props} value={value} onChange={setValue} />
}

export const WithMarkdown: Story = Template.bind({})
WithMarkdown.args = {
    value: `## Week notes

**Bold** and *italic* and ~~strikethrough~~ and a [link](https://posthog.com).

- Bullet one
- Bullet two

> A blockquote worth keeping.`,
}
