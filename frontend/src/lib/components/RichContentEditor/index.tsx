import './RichContentEditor.scss'

import { EditorContent, Extensions, useEditor } from '@tiptap/react'
import { BindLogic } from 'kea'
import { richContentEditorLogic } from './richContentEditorLogic'
import { cn } from 'lib/utils/css-classes'
import { PropsWithChildren } from 'react'
import { JSONContent, TTEditor } from './types'

export const RichContentEditor = ({
    logicKey,
    extensions,
    className,
    disabled = false,
    children,
    onCreate = () => {},
    onUpdate = () => {},
    onPressCmdEnter = () => {},
    onSelectionUpdate = () => {},
}: PropsWithChildren<{
    logicKey: string
    onCreate?: (editor: TTEditor) => void
    onUpdate?: (content: JSONContent) => void
    onPressCmdEnter?: () => void
    onSelectionUpdate?: () => void
    extensions: Extensions
    className?: string
    disabled?: boolean
}>): JSX.Element => {
    const editor = useEditor({
        extensions,
        onSelectionUpdate: onSelectionUpdate,
        onUpdate: ({ editor }) => onUpdate(editor.getJSON()),
        onCreate: ({ editor }) => onCreate(editor),
    })

    return (
        <EditorContent
            editor={editor}
            className={cn('RichContentEditor', className)}
            disabled={disabled}
            onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    if ((e.metaKey || e.ctrlKey) && onPressCmdEnter) {
                        onPressCmdEnter()
                        e.preventDefault()
                    }
                }
            }}
        >
            {editor && (
                <BindLogic logic={richContentEditorLogic} props={{ logicKey, editor }}>
                    {children}
                </BindLogic>
            )}
        </EditorContent>
    )
}
