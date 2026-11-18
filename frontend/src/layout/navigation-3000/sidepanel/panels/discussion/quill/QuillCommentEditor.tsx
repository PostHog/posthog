import { JSONContent } from '@tiptap/core'
import { Placeholder } from '@tiptap/extensions'
import { EditorContent } from '@tiptap/react'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { ReactNode, useRef, useState } from 'react'

import { IconEye, IconImage } from '@posthog/icons'
import { Button, InputGroup, InputGroupAddon, cn, toast } from '@posthog/quill'

import { useRichContentEditor } from 'lib/components/RichContentEditor'
import {
    DEFAULT_EXTENSIONS,
    DEFAULT_INITIAL_CONTENT,
    serializationOptions,
} from 'lib/components/RichContentEditor/LemonRichContentEditor'
import { RichContentEditorType, TTEditor } from 'lib/components/RichContentEditor/types'
import { createEditor } from 'lib/components/RichContentEditor/utils'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { emojiUsageLogic } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { QuillEmojiPickerPopover } from './QuillEmojiPickerPopover'

export interface QuillCommentEditorProps {
    initialContent?: JSONContent | null
    placeholder?: string
    onCreate?: (editor: RichContentEditorType) => void
    onUpdate?: (isEmpty: boolean) => void
    onPressCmdEnter?: () => void
    disabled?: boolean
    autoFocus?: boolean
    /** Controls shown in the toolbar before the preview toggle. */
    toolbarActions?: ReactNode
}

/** The discussion's rich text editor: mentions, emoji and images, in a quill frame with a preview toggle. */
export function QuillCommentEditor({
    initialContent,
    placeholder,
    onCreate,
    onUpdate,
    onPressCmdEnter,
    disabled = false,
    autoFocus = false,
    toolbarActions,
}: QuillCommentEditorProps): JSX.Element {
    const [previewShown, setPreviewShown] = useState(false)
    const [ttEditor, setTTEditor] = useState<TTEditor | null>(null)
    const { objectStorageAvailable } = useValues(preflightLogic)
    const { emojiUsed } = useActions(emojiUsageLogic)
    const fileInputRef = useRef<HTMLInputElement>(null)

    const editor = useRichContentEditor({
        extensions: [...DEFAULT_EXTENSIONS, Placeholder.configure({ placeholder })],
        onPressCmdEnter,
        disabled,
        autoFocus,
        initialContent: initialContent ?? DEFAULT_INITIAL_CONTENT,
        onCreate: (created) => {
            onCreate?.(createEditor(created))
            setTTEditor(created)
        },
        onUpdate: () => {
            if (onUpdate && ttEditor) {
                onUpdate(ttEditor.isEmpty)
            }
        },
    })

    const { setFilesToUpload, uploading } = useUploadFiles({
        onUpload: (url, fileName) => {
            ttEditor?.commands.insertContent(`\n\n![${fileName}](${url})`)
            // pinned: analytics event name, shared with the flag-off editor
            posthog.capture('rich text image uploaded', { name: fileName })
        },
        onError: (detail) => {
            // pinned: analytics event name, shared with the flag-off editor
            posthog.capture('rich text image upload failed', { error: detail })
            toast.error({ title: "Couldn't upload the image", description: detail })
        },
    })

    const uploadDisabledReason = objectStorageAvailable ? null : 'Enable object storage to add images'
    const previewText = ttEditor?.getText(serializationOptions)

    return (
        <InputGroup
            aria-disabled={disabled || undefined}
            className="items-stretch"
            onDragOver={(event) => {
                if (!uploadDisabledReason) {
                    event.preventDefault()
                }
            }}
            onDrop={(event) => {
                const images = Array.from(event.dataTransfer.files).filter((file) => file.type.startsWith('image/'))
                if (!uploadDisabledReason && images.length) {
                    event.preventDefault()
                    setFilesToUpload(images.slice(0, 1))
                }
            }}
        >
            {previewShown ? (
                <div className="min-h-16 w-full px-2.5 pt-2 text-[length:var(--text-ui,0.8125rem)]">
                    <LemonMarkdown lowKeyHeadings>{previewText || '_Nothing to preview_'}</LemonMarkdown>
                </div>
            ) : (
                <EditorContent
                    editor={editor}
                    className={cn(
                        'RichContentEditor w-full cursor-text text-[length:var(--text-ui,0.8125rem)]',
                        '[&_.ProseMirror]:min-h-16 [&_.ProseMirror]:px-2.5 [&_.ProseMirror]:pt-2 [&_.ProseMirror]:outline-none [&_p]:m-0'
                    )}
                />
            )}
            <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(event) => {
                    setFilesToUpload(Array.from(event.target.files ?? []))
                    event.target.value = ''
                }}
            />
            <InputGroupAddon align="block-end" className="w-full gap-0.5 px-1 pb-1">
                <Button
                    size="icon-sm"
                    aria-label="Add image"
                    tooltip="Add image"
                    loading={uploading}
                    disabledReason={previewShown ? 'Switch back to writing to add an image' : uploadDisabledReason}
                    onClick={() => fileInputRef.current?.click()}
                    data-attr="discussions-comment-add-image"
                >
                    <IconImage />
                </Button>
                <QuillEmojiPickerPopover
                    onSelect={(emoji) => {
                        ttEditor?.commands.insertContent(emoji)
                        emojiUsed(emoji)
                    }}
                    trigger={
                        <Button
                            size="icon-sm"
                            aria-label="Add emoji"
                            tooltip="Add emoji"
                            disabledReason={previewShown ? 'Switch back to writing to add an emoji' : null}
                            data-attr="lemon-rich-text-editor-emoji-popover"
                        />
                    }
                />
                <div className="ms-auto flex items-center gap-0.5">
                    {toolbarActions}
                    <Button
                        size="icon-sm"
                        aria-label="Preview"
                        tooltip="Preview"
                        aria-pressed={previewShown}
                        className="aria-pressed:bg-fill-selected aria-pressed:text-foreground"
                        onClick={() => setPreviewShown(!previewShown)}
                        data-attr="discussions-comment-preview"
                    >
                        <IconEye />
                    </Button>
                </div>
            </InputGroupAddon>
        </InputGroup>
    )
}
