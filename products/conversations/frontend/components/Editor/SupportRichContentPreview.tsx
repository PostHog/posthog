import './SupportEditor.scss'

import { JSONContent, getSchema } from '@tiptap/core'
import { Node as ProseMirrorNode } from '@tiptap/pm/model'
import { EditorContent } from '@tiptap/react'
import { useMemo } from 'react'

import { useRichContentEditor } from 'lib/components/RichContentEditor'
import { cn } from 'lib/utils/css-classes'

import { SUPPORT_PREVIEW_EXTENSIONS } from './SupportEditor'
import { SupportMarkdown } from './SupportMarkdown'
import { useImageLightbox } from './useImageLightbox'

const DEFAULT_INITIAL_CONTENT: JSONContent = {
    type: 'doc',
    content: [
        {
            type: 'paragraph',
            content: [],
        },
    ],
}

let previewSchema: ReturnType<typeof getSchema> | null = null

function isRenderableRichContent(content: JSONContent | null): content is JSONContent {
    if (!content) {
        return false
    }
    try {
        previewSchema = previewSchema ?? getSchema([...SUPPORT_PREVIEW_EXTENSIONS])
        ProseMirrorNode.fromJSON(previewSchema, content).check()
        return true
    } catch {
        return false
    }
}

export interface SupportRichContentPreviewProps {
    content: JSONContent | null
    className?: string
    /** Plain-text version of the message, rendered as markdown when `content` can't be parsed */
    fallbackContent?: string
    fallbackDisableImages?: boolean
}

/**
 * Preview component for rich content (tiptap JSON) with image support.
 * Renders in read-only mode with proper image styling.
 */
const editorImageFilter = (el: HTMLImageElement): boolean => el.classList.contains('SupportEditor__image')

export function SupportRichContentPreview({
    content,
    className,
    fallbackContent,
    fallbackDisableImages,
}: SupportRichContentPreviewProps): JSX.Element {
    const filter = useMemo(() => editorImageFilter, [])
    const { handleClick, lightbox } = useImageLightbox(filter)

    const renderable = useMemo(() => isRenderableRichContent(content), [content])

    const editor = useRichContentEditor({
        extensions: [...SUPPORT_PREVIEW_EXTENSIONS],
        disabled: true,
        initialContent: renderable && content ? content : DEFAULT_INITIAL_CONTENT,
    })

    if (!renderable) {
        return (
            <SupportMarkdown className={className} disableImages={fallbackDisableImages}>
                {fallbackContent ?? ''}
            </SupportMarkdown>
        )
    }

    return (
        <>
            <EditorContent
                editor={editor}
                className={cn('SupportRichContentPreview [&_.ProseMirror]:outline-none', className)}
                onClick={handleClick}
            />
            {lightbox}
        </>
    )
}
