import './RichContentEditor.scss'

import { EditorContent, Extensions, useEditor } from '@tiptap/react'
import { BindLogic } from 'kea'
import { PropsWithChildren, useEffect, useRef } from 'react'

import { cn } from 'lib/utils/css-classes'

import { CommandEnterExtension } from './CommandEnterExtension'
import { richContentEditorLogic } from './richContentEditorLogic'
import { JSONContent, TTEditor } from './types'

type RichContentEditorProps = {
    initialContent?: JSONContent
    onCreate?: (editor: TTEditor) => void
    onUpdate?: (content: JSONContent) => void
    onSelectionUpdate?: () => void
    onPressCmdEnter?: () => void
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
    onPressCmdEnter,
    autoFocus = false,
}: RichContentEditorProps): TTEditor => {
    // Extensions are fixed when the editor is created, so Cmd+Enter reads the latest callback through a ref.
    // A callback captured at creation would see the state of the first render, such as an empty composer.
    const onPressCmdEnterRef = useRef(onPressCmdEnter)
    onPressCmdEnterRef.current = onPressCmdEnter

    const editor = useEditor({
        shouldRerenderOnTransaction: false,
        // Only editors that submit on Cmd+Enter take the shortcut, because the extension swallows the keypress.
        extensions: onPressCmdEnter
            ? [
                  ...extensions,
                  CommandEnterExtension.configure({ onPressCmdEnter: () => onPressCmdEnterRef.current?.() }),
              ]
            : extensions,
        editable: !disabled,
        content: initialContent,
        autofocus: autoFocus,
        onSelectionUpdate: onSelectionUpdate,
        onUpdate: ({ editor }) => onUpdate(editor.getJSON()),
        onCreate: ({ editor }) => onCreate(editor),
    })

    useEffect(() => {
        editor.setOptions({ editable: !disabled })
    }, [editor, disabled])

    return editor
}
