import { JSONContent } from '@tiptap/core'
import { useEffect, useRef, useState } from 'react'

import { IconLock } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

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
    /** Extra actions rendered next to the send button */
    extraActions?: React.ReactNode
    /** Blocks sending customer-facing messages (private notes stay available). Shown as the button's disabled tooltip. */
    replyDisabledReason?: string | JSX.Element
    /** Whether draft mode is on: tints the composer green and confirms the recipient before sending */
    draftMode?: boolean
    /** Called when the draft-mode toggle changes; when provided, the toggle renders left of the send button */
    onDraftModeChange?: (enabled: boolean) => void
    /** Recipient description shown in the draft-mode send confirmation (e.g. "This will send to ...") */
    sendConfirmationMessage?: string
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
    extraActions,
    replyDisabledReason,
    draftMode = false,
    onDraftModeChange,
    sendConfirmationMessage,
}: MessageInputProps): JSX.Element {
    const [isEmpty, setIsEmpty] = useState(!draftContent)
    const [isUploading, setIsUploading] = useState(false)
    const [localIsPrivate, setLocalIsPrivate] = useState(false)
    const editorRef = useRef<RichContentEditorType | null>(null)
    const confirmOpenRef = useRef(false)

    useEffect(() => {
        setIsEmpty(!draftContent)
    }, [draftContent])

    // Support controlled or uncontrolled isPrivate
    const isPrivate = controlledIsPrivate ?? localIsPrivate
    const setIsPrivate = onPrivateChange ?? setLocalIsPrivate

    const handleSubmit = (): void => {
        // These guard the Cmd+Enter path, which bypasses the (disabled) button.
        if (replyDisabledReason && !isPrivate) {
            return
        }
        if (messageSending || isUploading) {
            return
        }
        if (editorRef.current && !isEmpty) {
            const richContent = editorRef.current.getJSON()
            const content = serializeToMarkdown(richContent)
            const doSend = (): void => {
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
            // Private notes are never sent externally, so they skip the draft-mode confirmation.
            if (draftMode && !isPrivate && sendConfirmationMessage) {
                // A rapid second Cmd+Enter would otherwise stack a duplicate dialog, since
                // messageSending only flips once Send is confirmed inside doSend.
                if (confirmOpenRef.current) {
                    return
                }
                confirmOpenRef.current = true
                LemonDialog.open({
                    title: 'Ready to send?',
                    description: sendConfirmationMessage,
                    primaryButton: { children: 'Send', type: 'primary', onClick: doSend },
                    secondaryButton: { children: 'Cancel' },
                    // Reset on every close path (confirm, cancel, Esc, backdrop) so the next send isn't blocked.
                    onAfterClose: () => {
                        confirmOpenRef.current = false
                    },
                })
            } else {
                doSend()
            }
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
                className={
                    isPrivate
                        ? 'bg-warning-highlight border-warning'
                        : draftMode
                          ? 'bg-success-highlight border-success'
                          : undefined
                }
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
                <div className="flex items-center gap-2">
                    {onDraftModeChange && (
                        <Tooltip title="In draft mode, sending asks you to confirm the recipient first.">
                            <span>
                                <LemonSwitch checked={draftMode} onChange={onDraftModeChange} label="Draft mode" />
                            </span>
                        </Tooltip>
                    )}
                    {extraActions}
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        loading={messageSending}
                        disabledReason={
                            replyDisabledReason && !isPrivate
                                ? replyDisabledReason
                                : isEmpty
                                  ? 'No message'
                                  : isUploading
                                    ? 'Uploading image...'
                                    : undefined
                        }
                    >
                        {isPrivate ? 'Attach' : buttonText}
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
