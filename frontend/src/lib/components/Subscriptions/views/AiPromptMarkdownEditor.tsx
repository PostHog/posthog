import { JSONContent } from '@tiptap/core'
import { Link } from '@tiptap/extension-link'
import { Placeholder } from '@tiptap/extension-placeholder'
import { MarkdownManager } from '@tiptap/markdown'
import { Extensions } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'

import { RichMarkdownEditor } from 'lib/components/MarkdownEditor/rich/RichMarkdownEditor'

const AI_PROMPT_PLACEHOLDER = 'e.g. Which events grew the most week-over-week? Highlight any unusual spikes.'

// A lean extension set — the prompt is free text fed to an LLM, so we skip images and task lists.
const AI_PROMPT_MARKDOWN_EXTENSIONS: Extensions = [
    StarterKit.configure({ heading: { levels: [1, 2, 3] }, link: false }),
    Link.configure({ openOnClick: false }),
]

const AI_PROMPT_EDITOR_EXTENSIONS: Extensions = [
    ...AI_PROMPT_MARKDOWN_EXTENSIONS,
    Placeholder.configure({ placeholder: AI_PROMPT_PLACEHOLDER }),
]

const markdownManager = new MarkdownManager({ extensions: AI_PROMPT_MARKDOWN_EXTENSIONS })

const EMPTY_DOC: JSONContent = { type: 'doc', content: [{ type: 'paragraph' }] }

function markdownToDoc(markdown: string | null | undefined): JSONContent {
    if (!markdown || markdown.trim() === '') {
        return EMPTY_DOC
    }

    try {
        const parsed = markdownManager.parse(markdown) as JSONContent
        if (parsed.type === 'doc') {
            return parsed
        }
    } catch {
        // Fall through to a plain paragraph for markdown we can't parse.
    }

    return { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: markdown }] }] }
}

function docToMarkdown(doc: JSONContent): string {
    try {
        return markdownManager.serialize(doc).trimEnd()
    } catch {
        return ''
    }
}

export function AiPromptMarkdownEditor({
    value,
    onChange,
    maxLength,
}: {
    value?: string | null
    onChange?: (value: string) => void
    maxLength?: number
}): JSX.Element {
    return (
        <RichMarkdownEditor
            value={value ?? ''}
            onChange={onChange}
            minRows={4}
            maxRows={16}
            maxLength={maxLength}
            dataAttr="ai-subscription-prompt-editor"
            extensions={AI_PROMPT_EDITOR_EXTENSIONS}
            markdownToDoc={markdownToDoc}
            docToMarkdown={docToMarkdown}
            showImageUpload={false}
        />
    )
}
