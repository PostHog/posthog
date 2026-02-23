import { JSONContent } from '@tiptap/core'
import { useEffect, useRef, useState } from 'react'

import { IconLock } from '@posthog/icons'
import { LemonButton, LemonCheckbox, Tooltip } from '@posthog/lemon-ui'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'

import { SupportEditor, serializeToMarkdown } from '../Editor'

export interface MessageInputProps {
    onSendMessage: (content: string, richContent: JSONContent | null, isPrivate: boolean, onSuccess: () => void) => void
    messageSending: boolean
    placeholder?: string
    buttonText?: string
    minRows?: number
    /** Whether to show the "Send as private" checkbox */
    showPrivateOption?: boolean
    /** Draft content to restore (from parent logic for tab persistence) */
    draftContent?: JSONContent | null
    /** Called when draft content changes */
    onDraftChange?: (content: JSONContent | null) => void
    /** Whether the private note checkbox is checked (from parent logic for tab persistence) */
    isPrivate?: boolean
    /** Called when private checkbox changes */
    onPrivateChange?: (isPrivate: boolean) => void
}

export function MessageInput({
    onSendMessage,
    messageSending,
    placeholder = 'Type your message...',
    buttonText = 'Send',
    minRows = 3,
    showPrivateOption = false,
    draftContent,
    onDraftChange,
    isPrivate: controlledIsPrivate,
    onPrivateChange,
}: MessageInputProps): JSX.Element {
    const [isEmpty, setIsEmpty] = useState(!draftContent)
    const [isUploading, setIsUploading] = useState(false)
    const [localIsPrivate, setLocalIsPrivate] = useState(false)
    const editorRef = useRef<RichContentEditorType | null>(null)

    useEffect(() => {
        setIsEmpty(!draftContent)
    }, [draftContent])

    // Support controlled or uncontrolled isPrivate
    const isPrivate = controlledIsPrivate ?? localIsPrivate
    const setIsPrivate = onPrivateChange ?? setLocalIsPrivate

    const handleSubmit = (): void => {
        if (editorRef.current && !isEmpty) {
            const richContent = editorRef.current.getJSON()
            const content = serializeToMarkdown(richContent)
            onSendMessage(content, richContent, isPrivate, () => {
                editorRef.current?.clear()
                setIsEmpty(true)
                onDraftChange?.(null)
                if (onPrivateChange) {
                    onPrivateChange(false)
                } else {
                    setLocalIsPrivate(false)
                }
            })
        }
    }

    const handleUpdate = (empty: boolean): void => {
        setIsEmpty(empty)
        if (onDraftChange && editorRef.current) {
            onDraftChange(empty ? null : editorRef.current.getJSON())
        }
    }

    return (
        <div>
            <SupportEditor
                initialContent={draftContent}
                placeholder={placeholder}
                onCreate={(editor) => {
                    editorRef.current = editor
                    if (draftContent) {
                        setIsEmpty(false)
                    }
                }}
                onUpdate={handleUpdate}
                onPressCmdEnter={handleSubmit}
                onUploadingChange={setIsUploading}
                disabled={messageSending}
                minRows={minRows}
                className={isPrivate ? 'bg-warning-highlight border-warning' : undefined}
            />
            <div className="flex justify-between items-center mt-2">
                {showPrivateOption ? (
                    <Tooltip title="Private notes are only visible to your team, not to the customer.">
                        <span>
                            <LemonCheckbox
                                checked={isPrivate}
                                onChange={setIsPrivate}
                                label={
                                    <span className="inline-flex items-center gap-1">
                                        <IconLock className="text-sm" />
                                        Attach as private note
                                    </span>
                                }
                            />
                        </span>
                    </Tooltip>
                ) : (
                    <div />
                )}
                <LemonButton
                    type="primary"
                    onClick={handleSubmit}
                    loading={messageSending}
                    disabledReason={isEmpty ? 'No message' : isUploading ? 'Uploading image...' : undefined}
                >
                    {isPrivate ? 'Attach' : buttonText}
                </LemonButton>
            </div>
        </div>
    )
}
