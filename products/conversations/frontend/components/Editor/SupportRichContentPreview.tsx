import './SupportEditor.scss'

import { JSONContent } from '@tiptap/core'
import { EditorContent } from '@tiptap/react'
import { useEffect, useMemo } from 'react'

import { useRichContentEditor } from 'lib/components/RichContentEditor'
import { cn } from 'lib/utils/css-classes'

import { isRenderableRichContent } from './isRenderableRichContent'
import { SUPPORT_PREVIEW_EXTENSIONS } from './SupportEditor'
import { SupportMarkdown } from './SupportMarkdown'
import { useImageLightbox } from './useImageLightbox'

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
    const renderable = useMemo(() => isRenderableRichContent(content), [content])

    if (!renderable || !content) {
        return (
            <SupportMarkdown className={className} disableImages={fallbackDisableImages}>
                {fallbackContent ?? ''}
            </SupportMarkdown>
        )
    }

    return <RichContentPreviewEditor content={content} className={className} />
}

function RichContentPreviewEditor({ content, className }: { content: JSONContent; className?: string }): JSX.Element {
    const filter = useMemo(() => editorImageFilter, [])
    const { handleClick, lightbox } = useImageLightbox(filter)

    const editor = useRichContentEditor({
        extensions: [...SUPPORT_PREVIEW_EXTENSIONS],
        disabled: true,
        initialContent: content,
    })

    // TipTap only applies initialContent once; push updates when note content changes in place.
    useEffect(() => {
        if (!editor) {
            return
        }
        const next = JSON.stringify(content)
        if (JSON.stringify(editor.getJSON()) !== next) {
            editor.commands.setContent(content, { emitUpdate: false })
        }
    }, [editor, content])

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
