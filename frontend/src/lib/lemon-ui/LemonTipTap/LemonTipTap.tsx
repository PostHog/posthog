import './LemonTipTap.scss'

import clsx from 'clsx'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Image from '@tiptap/extension-image'
import Typography from '@tiptap/extension-typography'
import React, { memo, useMemo, useEffect } from 'react'

interface LemonTipTapContainerProps {
    children: React.ReactNode
    className?: string
}

function LemonTipTapContainer({ children, className }: LemonTipTapContainerProps): JSX.Element {
    return <div className={clsx('LemonTipTap', className)}>{children}</div>
}

export interface LemonTipTapProps {
    children: string
    /** Whether headings should just be <strong> text. Recommended for item descriptions. */
    lowKeyHeadings?: boolean
    className?: string
}

const LemonTipTapRenderer = memo(function LemonTipTapRenderer({
    children,
    lowKeyHeadings = false,
}: LemonTipTapProps): JSX.Element {
    const extensions = useMemo(() => {
        return [
            StarterKit.configure({
                // Disable heading levels if lowKeyHeadings is true
                heading: lowKeyHeadings ? false : {},
            }),
            Image.configure({
                inline: true,
                allowBase64: true,
            }),
            Typography,
        ]
    }, [lowKeyHeadings])

    const editor = useEditor({
        extensions,
        content: '',
        editable: false,
    })

    // Update content when children changes
    useEffect(() => {
        if (editor && children) {
            // More idiomatic: let TipTap handle content parsing
            // Convert plain text/markdown to basic HTML structure
            const paragraphs = children
                .split('\n')
                .map((line) => (line.trim() ? `<p>${line}</p>` : '<p></p>'))
                .join('')
            editor.commands.setContent(paragraphs || '<p></p>')
        }
    }, [editor, children])

    if (!editor) {
        return <div>Loading...</div>
    }

    return <EditorContent editor={editor} />
})

/** Beautifully rendered Markdown with TipTap. */
function LemonTipTapComponent({ children, lowKeyHeadings = false, className }: LemonTipTapProps): JSX.Element {
    return (
        <LemonTipTapContainer className={className}>
            <LemonTipTapRenderer children={children} lowKeyHeadings={lowKeyHeadings} />
        </LemonTipTapContainer>
    )
}

export const LemonTipTap = Object.assign(LemonTipTapComponent, {
    Container: LemonTipTapContainer,
    Renderer: LemonTipTapRenderer,
})
