import './ToolbarRichTextEditor.scss'

import { Extensions, JSONContent } from '@tiptap/core'
import ExtensionDocument from '@tiptap/extension-document'
import { Placeholder } from '@tiptap/extensions'
import { EditorContent, useEditor } from '@tiptap/react'
import { BubbleMenu } from '@tiptap/react/menus'
import StarterKit from '@tiptap/starter-kit'
import { useEffect } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconBold, IconItalic } from 'lib/lemon-ui/icons'

export type ToolbarRichTextEditorProps = {
    initialContent?: JSONContent | null
    placeholder?: string
    onCreate?: (editor: ToolbarEditor) => void
    onUpdate?: (isEmpty: boolean) => void
    minRows?: number
}

export interface ToolbarEditor {
    getJSON: () => JSONContent
    setContent: (content: JSONContent) => void
    isEmpty: () => boolean
}

const DEFAULT_INITIAL_CONTENT: JSONContent = {
    type: 'doc',
    content: [
        {
            type: 'paragraph',
            content: [],
        },
    ],
}

const HeadingIcon = ({ level }: { level: number }): JSX.Element => (
    <div className="text-xs font-semibold">
        H<span className="text-[10px] font-bold">{level}</span>
    </div>
)

function buildExtensions(placeholder?: string): Extensions {
    const extensions: Extensions = [
        ExtensionDocument,
        StarterKit.configure({
            document: false,
            blockquote: false,
            code: false,
            codeBlock: false,
            horizontalRule: false,
            heading: { levels: [1, 2] },
        }),
    ]

    if (placeholder) {
        extensions.push(Placeholder.configure({ placeholder }))
    }

    return extensions
}

export function ToolbarRichTextEditor({
    initialContent,
    placeholder,
    onCreate,
    onUpdate,
    minRows,
}: ToolbarRichTextEditorProps): JSX.Element {
    const editor = useEditor({
        extensions: buildExtensions(placeholder),
        content: initialContent ?? DEFAULT_INITIAL_CONTENT,
        onUpdate: ({ editor: ed }) => {
            onUpdate?.(ed.isEmpty)
        },
    })

    useEffect(() => {
        if (editor && onCreate) {
            const toolbarEditor: ToolbarEditor = {
                getJSON: () => editor.getJSON(),
                setContent: (content: JSONContent) => editor.commands.setContent(content),
                isEmpty: () => editor.isEmpty,
            }
            onCreate(toolbarEditor)
        }
    }, [editor, onCreate])

    return (
        <div className="ToolbarRichTextEditor flex flex-col border rounded">
            {/* Always-visible formatting toolbar */}
            {editor && (
                <div className="flex items-center gap-0.5 p-1.5 border-b bg-bg-light">
                    <LemonButton
                        size="xsmall"
                        active={editor.isActive('heading', { level: 1 })}
                        onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
                        icon={<HeadingIcon level={1} />}
                        tooltip="Heading 1"
                    />
                    <LemonButton
                        size="xsmall"
                        active={editor.isActive('heading', { level: 2 })}
                        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
                        icon={<HeadingIcon level={2} />}
                        tooltip="Heading 2"
                    />
                    <div className="w-px h-4 bg-border mx-1" />
                    <LemonButton
                        size="xsmall"
                        active={editor.isActive('bold')}
                        onClick={() => editor.chain().focus().toggleBold().run()}
                        icon={<IconBold />}
                        tooltip="Bold"
                    />
                    <LemonButton
                        size="xsmall"
                        active={editor.isActive('italic')}
                        onClick={() => editor.chain().focus().toggleItalic().run()}
                        icon={<IconItalic />}
                        tooltip="Italic"
                    />
                </div>
            )}
            <EditorContent
                editor={editor}
                className="ToolbarRichContentEditor p-2 prose prose-sm max-w-none focus:outline-none [&_.ProseMirror]:focus:outline-none [&_.ProseMirror]:min-h-[3em]"
                style={minRows ? { minHeight: `${minRows * 1.5}em` } : undefined}
            />
            {editor && (
                <BubbleMenu
                    editor={editor}
                    options={{ placement: 'top-start' }}
                    shouldShow={({ editor: ed, state, from, to }) => {
                        return ed.isEditable && state.doc.textBetween(from, to).length > 0
                    }}
                >
                    <div
                        className="flex items-center gap-0.5"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            backgroundColor: '#fff',
                            border: '1px solid #d0d0d0',
                            borderRadius: '8px',
                            padding: '4px',
                            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
                            zIndex: 10,
                        }}
                    >
                        <LemonButton
                            size="xsmall"
                            active={editor.isActive('heading', { level: 1 })}
                            onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
                            icon={<HeadingIcon level={1} />}
                        />
                        <LemonButton
                            size="xsmall"
                            active={editor.isActive('heading', { level: 2 })}
                            onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
                            icon={<HeadingIcon level={2} />}
                        />
                        <LemonButton
                            size="xsmall"
                            active={editor.isActive('bold')}
                            onClick={() => editor.chain().focus().toggleBold().run()}
                            icon={<IconBold />}
                        />
                        <LemonButton
                            size="xsmall"
                            active={editor.isActive('italic')}
                            onClick={() => editor.chain().focus().toggleItalic().run()}
                            icon={<IconItalic />}
                        />
                    </div>
                </BubbleMenu>
            )}
        </div>
    )
}
