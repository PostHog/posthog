import { Placeholder } from '@tiptap/extension-placeholder'
import { Extensions } from '@tiptap/react'

import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { RichMarkdownEditor } from 'lib/components/MarkdownEditor/rich/RichMarkdownEditor'

import { markdownToTextCardDoc, textCardDocToMarkdown, TEXT_CARD_MARKDOWN_EXTENSIONS } from './textCardMarkdown'

const TEXT_CARD_MARKDOWN_EDITOR_EXTENSIONS: Extensions = [
    ...TEXT_CARD_MARKDOWN_EXTENSIONS,
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
            autoFocus
        />
    )
}
