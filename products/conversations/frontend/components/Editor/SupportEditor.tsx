import './SupportEditor.scss'

import { JSONContent, TextSerializer } from '@tiptap/core'
import ExtensionDocument from '@tiptap/extension-document'
import { Image } from '@tiptap/extension-image'
import { Underline } from '@tiptap/extension-underline'
import { Placeholder } from '@tiptap/extensions'
import { EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'

import { IconCode, IconImage } from '@posthog/icons'

import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { useRichContentEditor } from 'lib/components/RichContentEditor'
import { CommandEnterExtension } from 'lib/components/RichContentEditor/CommandEnterExtension'
import { MentionsExtension } from 'lib/components/RichContentEditor/MentionsExtension'
import { RichContentNodeMention } from 'lib/components/RichContentEditor/RichContentNodeMention'
import { RichContentEditorType, RichContentNodeType, TTEditor } from 'lib/components/RichContentEditor/types'
import { createEditor } from 'lib/components/RichContentEditor/utils'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { emojiUsageLogic } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconBold, IconItalic } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

// Underline icon (not in @posthog/icons)
function IconUnderline(): JSX.Element {
    return (
        <svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path
                d="M6 21h12M12 17a5 5 0 0 0 5-5V3M7 3v9a5 5 0 0 0 5 5"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
        </svg>
    )
}

export type SupportEditorProps = {
    initialContent?: JSONContent | null
    placeholder?: string
    onCreate?: (editor: RichContentEditorType) => void
    onUpdate?: (isEmpty: boolean) => void
    onPressCmdEnter?: () => void
    /** Called when upload state changes (true = uploading, false = idle) */
    onUploadingChange?: (uploading: boolean) => void
    disabled?: boolean
    minRows?: number
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

const ImageExtension = Image.configure({
    HTMLAttributes: {
        class: 'SupportEditor__image',
    },
    allowBase64: false,
})

export const SUPPORT_EXTENSIONS = [
    MentionsExtension,
    RichContentNodeMention,
    ExtensionDocument,
    StarterKit.configure({
        document: false,
        link: false,
        heading: false,
        blockquote: false,
        // bold: enabled - Cmd+B
        bulletList: false,
        // code: enabled - inline code (Cmd+E) - just visual styling, not executable
        codeBlock: false,
        // hardBreak: enabled - allows Shift+Enter for line breaks within paragraphs
        // dropcursor: enabled - shows visual indicator when dragging content
        // gapcursor: enabled - helps position cursor near images/blocks
        horizontalRule: false,
        // italic: enabled - Cmd+I
        listItem: false,
        listKeymap: false,
        orderedList: false,
        strike: false,
    }),
    Underline, // Cmd+U
    ImageExtension,
]

// Plain text serialization options for generateText() - used by Comment.tsx
// Extracts plain text with special handling for mentions and images
export const serializationOptions: { textSerializers?: Record<string, TextSerializer> } = {
    textSerializers: {
        [RichContentNodeType.Mention]: ({ node }) => `@member:${node.attrs.id}`,
        image: ({ node }) => `![${node.attrs.alt || 'image'}](${node.attrs.src})`,
        hardBreak: () => '\n',
    },
}

/**
 * Serialize tiptap JSON to markdown string.
 * Handles: bold, italic, code, images, mentions, hard breaks
 * Note: underline has no standard markdown syntax and is stripped
 */
export function serializeToMarkdown(content: JSONContent): string {
    return serializeNode(content).trim()
}

function serializeNode(node: JSONContent): string {
    if (!node) {
        return ''
    }

    // Handle text nodes with marks
    if (node.type === 'text') {
        let text = node.text || ''
        if (node.marks) {
            for (const mark of node.marks) {
                switch (mark.type) {
                    case 'bold':
                        text = `**${text}**`
                        break
                    case 'italic':
                        text = `*${text}*`
                        break
                    case 'code':
                        text = `\`${text}\``
                        break
                    // underline has no markdown equivalent, skip
                }
            }
        }
        return text
    }

    // Handle specific node types
    switch (node.type) {
        case 'doc':
            return (node.content || []).map(serializeNode).join('')

        case 'paragraph': {
            const content = (node.content || []).map(serializeNode).join('')
            return content + '\n\n'
        }

        case 'hardBreak':
            return '\n'

        case 'image':
            return `![${node.attrs?.alt || 'image'}](${node.attrs?.src || ''})`

        case RichContentNodeType.Mention:
            return `@member:${node.attrs?.id}`

        default:
            // For unknown nodes, try to serialize children
            if (node.content) {
                return (node.content || []).map(serializeNode).join('')
            }
            return ''
    }
}

export function SupportEditor({
    initialContent,
    placeholder,
    onCreate,
    onUpdate,
    onPressCmdEnter,
    onUploadingChange,
    disabled = false,
    minRows,
}: SupportEditorProps): JSX.Element {
    const [isDragging, setIsDragging] = useState<boolean>(false)
    const [ttEditor, setTTEditor] = useState<TTEditor | null>(null)
    // Force re-render when selection changes so toolbar buttons update their active state
    const [, setEditorState] = useState(0)
    const { objectStorageAvailable } = useValues(preflightLogic)
    const { emojiUsed } = useActions(emojiUsageLogic)
    const editor = useRichContentEditor({
        extensions: [
            ...SUPPORT_EXTENSIONS,
            Placeholder.configure({ placeholder }),
            CommandEnterExtension.configure({ onPressCmdEnter }),
        ],
        disabled,
        initialContent: initialContent ?? DEFAULT_INITIAL_CONTENT,
        onCreate: (editor) => {
            if (onCreate) {
                onCreate(createEditor(editor))
            }
            setTTEditor(editor)
        },
        onUpdate: () => {
            if (onUpdate && ttEditor) {
                onUpdate(ttEditor.isEmpty)
            }
            setEditorState((n) => n + 1)
        },
        onSelectionUpdate: () => {
            setEditorState((n) => n + 1)
        },
    })

    const dropRef = useRef<HTMLDivElement>(null)

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url, fileName) => {
            if (ttEditor) {
                ttEditor.chain().focus().setImage({ src: url, alt: fileName }).run()
            }
            posthog.capture('rich text image uploaded', { name: fileName })
        },
        onError: (detail) => {
            posthog.capture('rich text image upload failed', { error: detail })
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    // Notify parent of upload state changes
    useEffect(() => {
        onUploadingChange?.(uploading)
    }, [uploading, onUploadingChange])

    const handleDragEnter = (e: React.DragEvent): void => {
        e.preventDefault()
        if (e.dataTransfer.types.includes('Files')) {
            setIsDragging(true)
        }
    }

    const handleDragLeave = (e: React.DragEvent): void => {
        e.preventDefault()
        // Only set to false if we're leaving the container (not entering a child)
        if (e.currentTarget === e.target) {
            setIsDragging(false)
        }
    }

    const handleDragOver = (e: React.DragEvent): void => {
        e.preventDefault()
    }

    const handleDrop = (): void => {
        setIsDragging(false)
    }

    return (
        <div
            ref={dropRef}
            className={cn(
                'SupportEditor flex flex-col border rounded divide-y mt-4 input-like transition-shadow',
                isDragging && 'ring-2 ring-primary ring-offset-1'
            )}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
        >
            <EditorContent
                editor={editor}
                className="SupportEditor__content p-2"
                autoFocus
                style={minRows ? { minHeight: `${minRows * 1.5}em` } : undefined}
            />
            <div className="flex justify-between p-0.5">
                <div className="flex items-center">
                    <LemonButton
                        size="small"
                        active={ttEditor?.isActive('bold')}
                        onClick={() => ttEditor?.chain().focus().toggleBold().run()}
                        icon={<IconBold />}
                        tooltip="Bold (Cmd+B)"
                    />
                    <LemonButton
                        size="small"
                        active={ttEditor?.isActive('italic')}
                        onClick={() => ttEditor?.chain().focus().toggleItalic().run()}
                        icon={<IconItalic />}
                        tooltip="Italic (Cmd+I)"
                    />
                    <LemonButton
                        size="small"
                        active={ttEditor?.isActive('underline')}
                        onClick={() => ttEditor?.chain().focus().toggleUnderline().run()}
                        icon={<IconUnderline />}
                        tooltip="Underline (Cmd+U)"
                    />
                    <LemonButton
                        size="small"
                        active={ttEditor?.isActive('code')}
                        onClick={() => ttEditor?.chain().focus().toggleCode().run()}
                        icon={<IconCode />}
                        tooltip="Inline code (Cmd+E)"
                    />
                    <div className="w-px h-4 bg-border mx-1" />
                    <LemonFileInput
                        key="file-upload"
                        accept={'image/*'}
                        multiple={false}
                        alternativeDropTargetRef={dropRef}
                        onChange={setFilesToUpload}
                        loading={uploading}
                        value={filesToUpload}
                        showUploadedFiles={false}
                        callToAction={
                            <LemonButton
                                size="small"
                                icon={
                                    uploading ? (
                                        <Spinner className="text-lg" textColored={true} />
                                    ) : (
                                        <IconImage className="text-lg" />
                                    )
                                }
                                disabledReason={
                                    objectStorageAvailable
                                        ? undefined
                                        : 'Enable object storage to add images by dragging and dropping'
                                }
                                tooltip={objectStorageAvailable ? 'Click here or drag and drop to upload images' : null}
                            />
                        }
                    />
                    <EmojiPickerPopover
                        key="emoj-picker"
                        data-attr="lemon-rich-text-editor-emoji-popover"
                        onSelect={(emoji: string) => {
                            if (ttEditor) {
                                ttEditor.commands.insertContent(emoji)
                                emojiUsed(emoji)
                            }
                        }}
                    />
                </div>
            </div>
        </div>
    )
}
