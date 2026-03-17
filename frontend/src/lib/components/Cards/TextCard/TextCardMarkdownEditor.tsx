import { Color } from '@tiptap/extension-color'
import { Image } from '@tiptap/extension-image'
import { Link } from '@tiptap/extension-link'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { Placeholder } from '@tiptap/extension-placeholder'
import { TextAlign } from '@tiptap/extension-text-align'
import { TextStyle } from '@tiptap/extension-text-style'
import { Underline } from '@tiptap/extension-underline'
import { Extensions } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'

import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { RichMarkdownEditor } from 'lib/components/MarkdownEditor/RichMarkdownEditor'

import { markdownToTextCardDoc, textCardDocToMarkdown } from './textCardMarkdown'

const TEXT_CARD_MARKDOWN_EDITOR_EXTENSIONS: Extensions = [
    StarterKit.configure({
        heading: {
            levels: [1, 2, 3],
        },
        link: false,
    }),
    TaskList,
    TaskItem.configure({ nested: true }),
    Underline,
    TextStyle,
    Color,
    TextAlign.configure({
        types: ['heading', 'paragraph'],
    }),
    Link.configure({ openOnClick: false }),
    Image,
    Placeholder.configure({ placeholder: 'Write your markdown here...' }),
]

export function TextCardMarkdownEditor({
    value,
    onChange,
    minRows = 8,
    maxRows = 20,
}: {
    value?: string
    onChange?: (value: string) => void
    minRows?: number
    maxRows?: number
}): JSX.Element {
    return (
        <RichMarkdownEditor
            value={value}
            onChange={onChange}
            minRows={minRows}
            maxRows={maxRows}
            maxLength={4000}
            dataAttr="text-card-edit-area"
            extensions={TEXT_CARD_MARKDOWN_EDITOR_EXTENSIONS}
            markdownToDoc={markdownToTextCardDoc}
            docToMarkdown={textCardDocToMarkdown}
            renderPreview={(markdown) => <TextContent text={markdown} className="LemonTextArea--preview" />}
        />
    )
}
