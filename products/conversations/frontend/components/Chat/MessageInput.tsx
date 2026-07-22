import { JSONContent } from '@tiptap/core'
import { useEffect, useRef, useState } from 'react'

import { IconLock, IconUpload } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonFileInput,
    LemonInputSelect,
    LemonSnack,
    LemonSwitch,
    Tooltip,
} from '@posthog/lemon-ui'

import api from 'lib/api'
import { RichContentEditorType } from 'lib/components/RichContentEditor/types'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import type { TicketStatus } from '../../types'
import { SupportEditor, serializeToMarkdown } from '../Editor'

export interface ExtraRecipients {
    cc: string[]
    bcc: string[]
}

interface Attachment {
    id: string
    name: string
}

// Stable identity so the controlled LemonFileInput resets to empty after each pick (uploaded files
// are tracked in our own state), instead of accumulating and re-uploading on the next selection.
const NO_FILES: File[] = []

export interface MessageInputProps {
    onSendMessage: (
        content: string,
        richContent: JSONContent | null,
        isPrivate: boolean,
        onSuccess: () => void,
        statusAfterSend?: TicketStatus,
        extraRecipients?: ExtraRecipients,
        attachmentMediaIds?: string[]
    ) => void
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
    /** When provided, renders a dropdown next to the send button to send and set the ticket status in one go */
    sendAndSetStatusOptions?: { value: TicketStatus; statusLabel: string }[]
    /** Other unsaved ticket edits that sending with a status would also persist; when non-empty, asks for confirmation first */
    unsavedTicketChanges?: string[]
    /** Show Cc/Bcc recipient inputs (agent email replies only, not the customer widget) */
    showCcBcc?: boolean
    /** Allow attaching arbitrary files to the reply (agent email replies only) */
    showAttachments?: boolean
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
    sendAndSetStatusOptions,
    unsavedTicketChanges,
    showCcBcc = false,
    showAttachments = false,
}: MessageInputProps): JSX.Element {
    const [isEmpty, setIsEmpty] = useState(!draftContent)
    const [isUploading, setIsUploading] = useState(false)
    const [localIsPrivate, setLocalIsPrivate] = useState(false)
    const [cc, setCc] = useState<string[]>([])
    const [bcc, setBcc] = useState<string[]>([])
    const [ccBccExpanded, setCcBccExpanded] = useState(false)
    const [attachments, setAttachments] = useState<Attachment[]>([])
    const [attachmentUploading, setAttachmentUploading] = useState(false)
    const editorRef = useRef<RichContentEditorType | null>(null)

    const handleAttachmentUpload = async (files: File[]): Promise<void> => {
        if (files.length === 0) {
            return
        }
        setAttachmentUploading(true)
        try {
            const uploaded = await Promise.all(files.map((file) => api.conversationsTickets.uploadAttachment(file)))
            setAttachments((current) => [...current, ...uploaded.map((u) => ({ id: u.id, name: u.name }))])
        } catch {
            lemonToast.error('Failed to upload attachment')
        } finally {
            setAttachmentUploading(false)
        }
    }

    useEffect(() => {
        setIsEmpty(!draftContent)
    }, [draftContent])

    // Support controlled or uncontrolled isPrivate
    const isPrivate = controlledIsPrivate ?? localIsPrivate
    const setIsPrivate = onPrivateChange ?? setLocalIsPrivate

    const sendVerb = isPrivate ? 'Attach' : 'Send'

    const handleSubmit = (statusAfterSend?: TicketStatus): void => {
        // These guard the Cmd+Enter path, which bypasses the (disabled) button.
        if (replyDisabledReason && !isPrivate) {
            return
        }
        if (messageSending || isUploading || attachmentUploading) {
            return
        }
        if (editorRef.current && !isEmpty) {
            const richContent = editorRef.current.getJSON()
            const content = serializeToMarkdown(richContent)
            // Cc/Bcc and attachments only apply to customer-facing replies, never private notes.
            const extraRecipients = showCcBcc && !isPrivate ? { cc, bcc } : undefined
            const attachmentMediaIds =
                showAttachments && !isPrivate && attachments.length > 0 ? attachments.map((a) => a.id) : undefined
            const doSend = (): void => {
                onSendMessage(
                    content,
                    richContent,
                    isPrivate,
                    () => {
                        editorRef.current?.clear()
                        setIsEmpty(true)
                        onDraftChange?.(null)
                        setCc([])
                        setBcc([])
                        setCcBccExpanded(false)
                        setAttachments([])
                        if (onPrivateChange) {
                            onPrivateChange(false)
                        } else {
                            setLocalIsPrivate(false)
                        }
                    },
                    statusAfterSend,
                    extraRecipients,
                    attachmentMediaIds
                )
            }
            // Sending with a status saves the whole ticket, so surface any other unsaved edits first.
            if (statusAfterSend && unsavedTicketChanges && unsavedTicketChanges.length > 0) {
                LemonDialog.open({
                    title: `${sendVerb} and save other changes?`,
                    description: (
                        <>
                            <p>
                                {isPrivate ? 'Attaching' : 'Sending'} will also save your other unsaved ticket changes:
                            </p>
                            <ul className="list-disc pl-5">
                                {unsavedTicketChanges.map((change) => (
                                    <li key={change}>{change}</li>
                                ))}
                            </ul>
                            {draftMode && !isPrivate && sendConfirmationMessage ? (
                                <p>{sendConfirmationMessage}</p>
                            ) : null}
                        </>
                    ),
                    primaryButton: { children: `${sendVerb} and save`, type: 'primary', onClick: doSend },
                    secondaryButton: { children: 'Cancel' },
                })
            } else if (draftMode && !isPrivate && sendConfirmationMessage) {
                // Private notes are never sent externally, so they skip the draft-mode confirmation.
                LemonDialog.open({
                    title: 'Ready to send?',
                    description: sendConfirmationMessage,
                    primaryButton: { children: 'Send', type: 'primary', onClick: doSend },
                    secondaryButton: { children: 'Cancel' },
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

    const sendBlockedReason =
        replyDisabledReason && !isPrivate
            ? replyDisabledReason
            : isEmpty
              ? 'No message'
              : isUploading
                ? 'Uploading image...'
                : attachmentUploading
                  ? 'Uploading attachment...'
                  : undefined

    const showCcBccFields = showCcBcc && !isPrivate
    const ccBccVisible = ccBccExpanded || cc.length > 0 || bcc.length > 0

    return (
        <div>
            {showCcBccFields &&
                (ccBccVisible ? (
                    <div className="flex flex-col gap-1 mb-2">
                        <div className="flex items-center gap-2">
                            <span className="text-muted text-xs w-8 shrink-0">Cc</span>
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                value={cc}
                                onChange={setCc}
                                placeholder="Add Cc recipients..."
                                size="small"
                                className="flex-1"
                            />
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="text-muted text-xs w-8 shrink-0">Bcc</span>
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                value={bcc}
                                onChange={setBcc}
                                placeholder="Add Bcc recipients..."
                                size="small"
                                className="flex-1"
                            />
                        </div>
                    </div>
                ) : (
                    <div className="mb-2">
                        <LemonButton size="xsmall" type="tertiary" onClick={() => setCcBccExpanded(true)}>
                            Add Cc/Bcc
                        </LemonButton>
                    </div>
                ))}
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
                onPressCmdEnter={() => handleSubmit()}
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
            {showAttachments && !isPrivate && (
                <div className="flex flex-wrap items-center gap-1 mt-2">
                    {attachments.map((attachment) => (
                        <LemonSnack
                            key={attachment.id}
                            onClose={() => setAttachments((current) => current.filter((a) => a.id !== attachment.id))}
                        >
                            {attachment.name}
                        </LemonSnack>
                    ))}
                    <LemonFileInput
                        accept="*/*"
                        multiple
                        value={NO_FILES}
                        showUploadedFiles={false}
                        loading={attachmentUploading}
                        onChange={(files) => void handleAttachmentUpload(files)}
                        callToAction={
                            <LemonButton
                                size="small"
                                type="tertiary"
                                icon={<IconUpload />}
                                loading={attachmentUploading}
                            >
                                Attach file
                            </LemonButton>
                        }
                    />
                </div>
            )}
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
                        <Tooltip
                            title={isPrivate ? null : 'In draft mode, sending asks you to confirm the recipient first.'}
                        >
                            <span>
                                <LemonSwitch
                                    checked={draftMode}
                                    onChange={onDraftModeChange}
                                    label="Draft mode"
                                    disabledReason={isPrivate ? 'Draft mode has no effect on private notes' : undefined}
                                />
                            </span>
                        </Tooltip>
                    )}
                    {extraActions}
                    <LemonButton
                        type="primary"
                        onClick={() => handleSubmit()}
                        loading={messageSending}
                        disabledReason={sendBlockedReason}
                        sideAction={
                            sendAndSetStatusOptions?.length
                                ? {
                                      'aria-label': `${sendVerb} and set ticket status`,
                                      disabled: messageSending,
                                      disabledReason: sendBlockedReason,
                                      dropdown: {
                                          placement: 'bottom-end',
                                          overlay: sendAndSetStatusOptions.map((option) => (
                                              <LemonButton
                                                  key={option.value}
                                                  fullWidth
                                                  size="small"
                                                  onClick={() => handleSubmit(option.value)}
                                              >
                                                  {`${sendVerb} and set ${option.statusLabel}`}
                                              </LemonButton>
                                          )),
                                      },
                                  }
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
