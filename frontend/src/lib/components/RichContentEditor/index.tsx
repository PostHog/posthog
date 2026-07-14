import './RichContentEditor.scss'

import { EditorContent, Extensions, useEditor } from '@tiptap/react'
import { BindLogic } from 'kea'
import { PropsWithChildren, useEffect } from 'react'

import { cn } from 'lib/utils/css-classes'

import { richContentEditorLogic } from './richContentEditorLogic'
import { JSONContent, TTEditor } from './types'

type RichContentEditorProps = {
    initialContent?: JSONContent
    onCreate?: (editor: TTEditor) => void
    onUpdate?: (content: JSONContent) => void
    onSelectionUpdate?: () => void
    extensions: Extensions
    disabled?: boolean
    autoFocus?: boolean
}

export const RichContentEditor = ({
    logicKey,
    className,
    children,
    disabled = false,
    autoFocus = false,
    ...editorProps
}: PropsWithChildren<
    {
        logicKey: string
        className?: string
        autoFocus?: boolean
    } & RichContentEditorProps
>): JSX.Element => {
    const editor = useRichContentEditor(editorProps)

    useEffect(() => {
        editor.setOptions({ editable: !disabled })
    }, [editor, disabled])

    return (
        <EditorContent
            editor={editor}
            className={cn('RichContentEditor', className)}
            autoFocus={autoFocus}
            spellCheck={editor.isFocused}
        >
            {editor && (
                <BindLogic logic={richContentEditorLogic} props={{ logicKey, editor }}>
                    {children}
                </BindLogic>
            )}
        </EditorContent>
    )
}

export const useRichContentEditor = ({
    extensions,
    disabled,
    initialContent,
    onCreate = () => {},
    onUpdate = () => {},
    onSelectionUpdate = () => {},
}: RichContentEditorProps): TTEditor => {
    const editor = useEditor({
        shouldRerenderOnTransaction: false,
        extensions,
        editable: !disabled,
        content: initialContent,
        onSelectionUpdate: onSelectionUpdate,
        onUpdate: ({ editor }) => onUpdate(editor.getJSON()),
        onCreate: ({ editor }) => onCreate(editor),
    })

    useEffect(() => {
        editor.setOptions({ editable: !disabled })
    }, [editor, disabled])

    return editor
}
