import { JSONContent } from '@tiptap/core'
import { Placeholder } from '@tiptap/extensions'
import { EditorContent } from '@tiptap/react'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { ReactNode, useRef, useState } from 'react'

import { IconEye, IconImage } from '@posthog/icons'
import { Button, Toggle, Tooltip, TooltipContent, TooltipTrigger, cn, toast } from '@posthog/quill'

import { useRichContentEditor } from 'lib/components/RichContentEditor'
import { CommandEnterExtension } from 'lib/components/RichContentEditor/CommandEnterExtension'
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

interface QuillCommentEditorProps {
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
        extensions: [
            ...DEFAULT_EXTENSIONS,
            Placeholder.configure({ placeholder }),
            CommandEnterExtension.configure({ onPressCmdEnter }),
        ],
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
        <div
            className={cn(
                'flex flex-col rounded-md border border-input bg-background focus-within:border-ring',
                disabled && 'opacity-60'
            )}
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
                <div className="min-h-16 px-2.5 py-2 text-xs">
                    <LemonMarkdown lowKeyHeadings>{previewText || '_Nothing to preview_'}</LemonMarkdown>
                </div>
            ) : (
                <EditorContent
                    editor={editor}
                    className={cn(
                        'RichContentEditor min-h-16 px-2.5 py-2 text-xs',
                        '[&_.ProseMirror]:outline-none [&_p]:m-0'
                    )}
                />
            )}
            <div className="flex items-center gap-0.5 p-1">
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
                    <Tooltip>
                        <TooltipTrigger
                            delay={0}
                            render={
                                <Toggle
                                    size="icon"
                                    className="size-7"
                                    aria-label="Preview"
                                    pressed={previewShown}
                                    onPressedChange={setPreviewShown}
                                    data-attr="discussions-comment-preview"
                                />
                            }
                        >
                            <IconEye />
                        </TooltipTrigger>
                        <TooltipContent>Preview</TooltipContent>
                    </Tooltip>
                </div>
            </div>
        </div>
    )
}
