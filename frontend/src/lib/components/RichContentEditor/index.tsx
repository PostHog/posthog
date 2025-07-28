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
    onUpdate,
    onSelectionUpdate,
    onCreate,
    onDrop,
    onPaste,
}: PropsWithChildren<{
    logicKey: string
    onUpdate?: () => void
    onSelectionUpdate?: () => void
    onCreate?: (editor: TTEditor) => void
    extensions: Extensions
    className?: string
    onDrop?: (
        dataTransfer: DataTransfer | null,
        coordinates: { pos: number; inside: number } | null,
        moved: boolean,
        insertContent: (position: number, content: JSONContent) => void
    ) => boolean | void
    onPaste?: (clipboardData: DataTransfer | null, insertContent: (content: JSONContent) => void) => void
}>): JSX.Element => {
    const editor = useEditor({
        extensions,
        editorProps: {
            handleDrop: onDrop
                ? (view, event, _, moved) => {
                      const coordinates = view.posAtCoords({ left: event.clientX, top: event.clientY })

                      if (!editor) {
                          return false
                      }

                      const insertContent = (position: number, content: JSONContent): boolean =>
                          editor.chain().focus().setTextSelection(position).insertContent(content).run()

                      return onDrop(event.dataTransfer, coordinates, moved, insertContent)
                  }
                : undefined,
            handlePaste: onPaste
                ? (_view, event) => {
                      if (!editor) {
                          return false
                      }

                      const insertContent = (content: JSONContent): boolean =>
                          editor.chain().focus().insertContent(content).run()

                      onPaste(event.clipboardData, insertContent)
                  }
                : undefined,
        },
        onUpdate,
        onSelectionUpdate,
        onCreate: ({ editor }) => onCreate?.(editor),
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
