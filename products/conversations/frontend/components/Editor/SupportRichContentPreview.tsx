import './SupportEditor.scss'

import { JSONContent } from '@tiptap/core'
import { EditorContent } from '@tiptap/react'

import { useRichContentEditor } from 'lib/components/RichContentEditor'
import { cn } from 'lib/utils/css-classes'

import { SUPPORT_EXTENSIONS } from './SupportEditor'

const DEFAULT_INITIAL_CONTENT: JSONContent = {
    type: 'doc',
    content: [
        {
            type: 'paragraph',
            content: [],
        },
    ],
}

export interface SupportRichContentPreviewProps {
    content: JSONContent | null
    className?: string
}

/**
 * Preview component for rich content (tiptap JSON) with image support.
 * Renders in read-only mode with proper image styling.
 */
export function SupportRichContentPreview({ content, className }: SupportRichContentPreviewProps): JSX.Element {
    const editor = useRichContentEditor({
        extensions: [...SUPPORT_EXTENSIONS],
        disabled: true,
        initialContent: content ?? DEFAULT_INITIAL_CONTENT,
    })
    return (
        <EditorContent
            editor={editor}
            className={cn('SupportRichContentPreview [&_.ProseMirror]:outline-none', className)}
        />
    )
}
