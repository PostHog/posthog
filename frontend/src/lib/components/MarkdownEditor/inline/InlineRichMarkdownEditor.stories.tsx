import type { Meta, StoryObj } from '@storybook/react'
import { Placeholder } from '@tiptap/extension-placeholder'
import { useState } from 'react'

import {
    markdownToTextCardDoc,
    textCardDocToMarkdown,
    TEXT_CARD_MARKDOWN_EXTENSIONS,
} from 'lib/components/Cards/TextCard/textCardMarkdown'

import { InlineRichMarkdownEditor, InlineRichMarkdownEditorProps } from './InlineRichMarkdownEditor'

const INLINE_EXTENSIONS = [
    ...TEXT_CARD_MARKDOWN_EXTENSIONS,
    Placeholder.configure({ placeholder: 'Select text to open the bubble menu…' }),
]

const INLINE_EXTENSIONS_BUBBLE_AND_SLASH = [
    ...TEXT_CARD_MARKDOWN_EXTENSIONS,
    Placeholder.configure({
        placeholder: 'Select text for the bubble menu, or type / for slash commands…',
    }),
]

const storyDefaults = {
    extensions: INLINE_EXTENSIONS,
    markdownToDoc: markdownToTextCardDoc,
    docToMarkdown: textCardDocToMarkdown,
    dataAttr: 'story-inline-rich-markdown-editor',
}

type Story = StoryObj<InlineRichMarkdownEditorProps>

const meta: Meta<InlineRichMarkdownEditorProps> = {
    title: 'Components/Markdown editor/Inline',
    component: InlineRichMarkdownEditor,
    tags: ['autodocs'],
    render: (props) => {
        const [value, setValue] = useState(props.value ?? '')
        return <InlineRichMarkdownEditor {...storyDefaults} {...props} value={value} onChange={setValue} />
    },
}

export default meta

export const WithMarkdown: Story = {
    args: {
        value: `Select this paragraph to format it with the bubble menu.

## Or use headings

**Bold** and *italic* work too.`,
    },
}

export const WithSlashCommands: Story = {
    args: {
        value: 'Type / in the editor to open the command menu.',
        showSlashCommands: true,
    },
}

/** Bubble menu (selection) and `/` slash menu both enabled — default in product, shown here with helper copy. */
export const BubbleMenuAndSlashCommands: Story = {
    args: {
        extensions: INLINE_EXTENSIONS_BUBBLE_AND_SLASH,
        value: `Select this sentence to open the **bubble** toolbar (bold, link, image, emoji, etc.).

On a new line, type \`/\` to open **slash** commands — same capabilities grouped as Style and Insert.`,
        showSlashCommands: true,
        showBubbleImageUpload: true,
        showBubbleEmoji: true,
    },
}
