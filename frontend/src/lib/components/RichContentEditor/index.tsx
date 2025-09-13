import './RichContentEditor.scss'

import { EditorContent, Extensions, useEditor } from '@tiptap/react'
import { BindLogic } from 'kea'
import { PropsWithChildren, useEffect } from 'react'

import { cn } from 'lib/utils/css-classes'

import { richContentEditorLogic } from './richContentEditorLogic'
import { JSONContent, TTEditor } from './types'

export const RichContentEditor = ({
    logicKey,
    extensions,
    className,
    children,
    initialContent = [],
    disabled = false,
    onCreate = () => {},
    onUpdate = () => {},
    onSelectionUpdate = () => {},
    autoFocus = false,
}: PropsWithChildren<{
    logicKey: string
    initialContent?: JSONContent
    onCreate?: (editor: TTEditor) => void
    onUpdate?: (content: JSONContent) => void
    onSelectionUpdate?: () => void
    extensions: Extensions
    disabled?: boolean
    className?: string
    autoFocus?: boolean
}>): JSX.Element => {
    const editor = useEditor({
        shouldRerenderOnTransaction: true,
        extensions,
        editable: !disabled,
        content: initialContent ?? [],
        onSelectionUpdate: onSelectionUpdate,
        onUpdate: ({ editor }) => onUpdate(editor.getJSON()),
        onCreate: ({ editor }) => onCreate(editor),
    })

    useEffect(() => {
        editor.setOptions({ editable: !disabled })
    }, [editor, disabled])

    return (
        <EditorContent editor={editor} className={cn('RichContentEditor', className)} autoFocus={autoFocus}>
            {editor && (
                <BindLogic logic={richContentEditorLogic} props={{ logicKey, editor }}>
                    {children}
                </BindLogic>
            )}
        </EditorContent>
    )
}
