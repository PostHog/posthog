import { EditorContent } from '@tiptap/react'
import clsx from 'clsx'
import { HTMLAttributes, memo, useEffect, useMemo } from 'react'

import 'lib/components/MarkdownEditor/shared/RichMarkdownEditor.scss'
import { useRichContentEditor } from 'lib/components/RichContentEditor'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { TEXT_CARD_MARKDOWN_READONLY_EXTENSIONS, textCardConverter } from './textCardMarkdown'

export interface TextContentProps extends Pick<HTMLAttributes<HTMLDivElement>, 'className'> {
    text: string
    closeDetails?: () => void
}

function TextContentImpl({ text, closeDetails, className }: TextContentProps): JSX.Element {
    const initialDoc = useMemo(() => textCardConverter.markdownToDoc(text), [text])

    const editor = useRichContentEditor({
        extensions: TEXT_CARD_MARKDOWN_READONLY_EXTENSIONS,
        initialContent: initialDoc,
        disabled: true,
    })

    useEffect(() => {
        if (!editor) {
            return
        }

        editor.commands.setContent(initialDoc, { emitUpdate: false })
    }, [editor, initialDoc])

    return (
        <div className={clsx('w-full', className)} onClick={() => closeDetails?.()}>
            {editor ? (
                <div className="RichMarkdownEditor overflow-auto">
                    <EditorContent editor={editor} className="RichMarkdownEditor__content px-0 py-0" />
                </div>
            ) : (
                <LemonMarkdown className="overflow-auto">{text}</LemonMarkdown>
            )}
        </div>
    )
}

export const TextContent = memo(TextContentImpl)
TextContent.displayName = 'TextContent'
