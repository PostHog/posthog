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
    children,
    onCreate = () => {},
    onUpdate = () => {},
    onSelectionUpdate = () => {},
}: PropsWithChildren<{
    logicKey: string
    onCreate?: (editor: TTEditor) => void
    onUpdate?: (content: JSONContent) => void
    onSelectionUpdate?: () => void
    extensions: Extensions
    className?: string
}>): JSX.Element => {
    const editor = useEditor({
        // this is disabled by default since v3
        // leaving it enabled to preserve functionality across version upgrades
        // we should try switching it (performance gains) and see if it causes any issues
        shouldRerenderOnTransaction: true,
        extensions,
        onSelectionUpdate: onSelectionUpdate,
        onUpdate: ({ editor }) => onUpdate(editor.getJSON()),
        onCreate: ({ editor }) => onCreate(editor),
    })

    return (
        <EditorContent editor={editor} className={cn('RichContentEditor', className)}>
            {editor && (
                <BindLogic logic={richContentEditorLogic} props={{ logicKey, editor }}>
                    {children}
                </BindLogic>
            )}
        </EditorContent>
    )
}
