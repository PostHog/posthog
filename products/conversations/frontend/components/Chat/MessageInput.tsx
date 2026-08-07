import { JSONContent } from '@tiptap/core'
import { useEffect, useRef, useState } from 'react'

import { IconLock } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import type { TicketChannel, TicketStatus } from '../../types'
import { channelIcon, getReplyPlaceholder, hasReplyChannelBranding } from '../Channels/ChannelsTag'
import { SupportEditor, serializeToMarkdown } from '../Editor'

export interface MessageInputProps {
    onSendMessage: (
        content: string,
        richContent: JSONContent | null,
        isPrivate: boolean,
        onSuccess: () => void,
        statusAfterSend?: TicketStatus
    ) => void
    messageSending: boolean
    placeholder?: string
    /** Channel the ticket came from; drives the default placeholder and the send-button logo */
    channel?: TicketChannel
    buttonText?: string
    minRows?: number
    /** Whether to show the "Send as private" checkbox */
    showPrivateOption?: boolean
    /** Draft content to restore (from parent logic for tab persistence) */
    draftContent?: JSONContent | string | null
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
    /** Blocks sending entirely, including private notes (e.g. the user lacks edit access). Takes precedence. */
    sendDisabledReason?: string | JSX.Element
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
    /** When set, the composer is editing an existing private note */
    editingMessageId?: string | null
    /** Cancel edit mode and restore the previous draft */
    onCancelEdit?: () => void
}

export function MessageInput({
    onSendMessage,
    messageSending,
    placeholder,
    channel,
    buttonText = 'Send',
    minRows = 3,
    showPrivateOption = false,
    draftContent,
    onDraftChange,
    isPrivate: controlledIsPrivate,
    onPrivateChange,
    extraActions,
    replyDisabledReason,
    sendDisabledReason,
    draftMode = false,
    onDraftModeChange,
    sendConfirmationMessage,
    sendAndSetStatusOptions,
    unsavedTicketChanges,
    editingMessageId = null,
    onCancelEdit,
}: MessageInputProps): JSX.Element {
    const [isEmpty, setIsEmpty] = useState(!draftContent)
    const [isUploading, setIsUploading] = useState(false)
    const [localIsPrivate, setLocalIsPrivate] = useState(false)
    const editorRef = useRef<RichContentEditorType | null>(null)
    const lastSeededEditId = useRef<string | null>(null)
    const draftContentRef = useRef(draftContent)
    draftContentRef.current = draftContent
    const isEditing = !!editingMessageId

    useEffect(() => {
        setIsEmpty(!draftContent)
    }, [draftContent])

    // SupportEditor only applies initialContent at mount; seed/restore via setContent on edit transitions.
    // Defer seeding so kea listeners can apply setDraftContent before we read it.
    useEffect(() => {
        const editor = editorRef.current
        if (!editor) {
            return
        }

        if (!editingMessageId) {
            if (lastSeededEditId.current !== null) {
                lastSeededEditId.current = null
                const content = draftContentRef.current
                if (content) {
                    editor.setContent(content)
                    queueMicrotask(() => setIsEmpty(editor.isEmpty()))
                } else {
                    editor.clear()
                    setIsEmpty(true)
                }
            }
            return
        }

        if (lastSeededEditId.current === editingMessageId) {
            return
        }
        const targetId = editingMessageId
        queueMicrotask(() => {
            const ed = editorRef.current
            if (!ed || lastSeededEditId.current === targetId) {
                return
            }
            const content = draftContentRef.current
            if (content == null) {
                return
            }
            lastSeededEditId.current = targetId
            ed.setContent(content)
            queueMicrotask(() => setIsEmpty(ed.isEmpty()))
        })
    }, [editingMessageId])

    // Support controlled or uncontrolled isPrivate
    const isPrivate = controlledIsPrivate ?? localIsPrivate
    const setIsPrivate = onPrivateChange ?? setLocalIsPrivate

    const resolvedPlaceholder =
        placeholder ??
        (isEditing
            ? 'Edit your private note...'
            : isPrivate
              ? 'Type your private note...'
              : getReplyPlaceholder(channel))
    const showChannelLogo = !isPrivate && !isEditing && hasReplyChannelBranding(channel)
    const sendVerb = isEditing ? 'Save' : isPrivate ? 'Attach' : 'Send'

    const handleSubmit = (statusAfterSend?: TicketStatus): void => {
        // These guard the Cmd+Enter path, which bypasses the disabled button.
        if (sendDisabledReason || (replyDisabledReason && !isPrivate && !isEditing)) {
            return
        }
        if (messageSending || isUploading) {
            return
        }
        if (editorRef.current && !isEmpty) {
            const richContent = editorRef.current.getJSON()
            const content = serializeToMarkdown(richContent)
            const doSend = (): void => {
                onSendMessage(
                    content,
                    richContent,
                    isPrivate,
                    () => {
                        editorRef.current?.clear()
                        setIsEmpty(true)
                        onDraftChange?.(null)
                        if (onPrivateChange) {
                            onPrivateChange(false)
                        } else {
                            setLocalIsPrivate(false)
                        }
                    },
                    isEditing ? undefined : statusAfterSend
                )
            }
            // Sending with a status saves the whole ticket, so surface any other unsaved edits first.
            if (!isEditing && statusAfterSend && unsavedTicketChanges && unsavedTicketChanges.length > 0) {
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
            } else if (!isEditing && draftMode && !isPrivate && sendConfirmationMessage) {
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

    const sendBlockedReason = sendDisabledReason
        ? sendDisabledReason
        : replyDisabledReason && !isPrivate && !isEditing
          ? replyDisabledReason
          : isEmpty
            ? 'No message'
            : isUploading
              ? 'Uploading image...'
              : undefined
    const sendControlDisabledReason =
        typeof sendDisabledReason === 'string'
            ? sendDisabledReason
            : sendDisabledReason
              ? 'Sending is disabled'
              : undefined

    return (
        <div>
            <SupportEditor
                initialContent={typeof draftContent === 'string' ? null : draftContent}
                placeholder={resolvedPlaceholder}
                onCreate={(editor) => {
                    editorRef.current = editor
                    if (draftContent) {
                        editor.setContent(draftContent)
                        setIsEmpty(false)
                    }
                }}
                onUpdate={handleUpdate}
                onPressCmdEnter={() => handleSubmit()}
                onUploadingChange={setIsUploading}
                disabled={messageSending || !!sendDisabledReason}
                minRows={minRows}
                className={
                    isPrivate || isEditing
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
                                checked={isPrivate || isEditing}
                                onChange={setIsPrivate}
                                disabledReason={isEditing ? 'Editing a private note' : sendControlDisabledReason}
                                label={
                                    <span className="inline-flex items-center gap-1">
                                        <IconLock className="text-sm" />
                                        {isEditing ? 'Editing private note' : 'Attach as private note'}
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
                            title={
                                isPrivate || isEditing
                                    ? null
                                    : 'In draft mode, sending asks you to confirm the recipient first.'
                            }
                        >
                            <span>
                                <LemonSwitch
                                    checked={draftMode}
                                    onChange={onDraftModeChange}
                                    label="Draft mode"
                                    disabledReason={
                                        sendControlDisabledReason ??
                                        (isPrivate || isEditing
                                            ? 'Draft mode has no effect on private notes'
                                            : undefined)
                                    }
                                />
                            </span>
                        </Tooltip>
                    )}
                    {extraActions}
                    {isEditing && onCancelEdit && (
                        <LemonButton type="secondary" onClick={onCancelEdit} disabled={messageSending}>
                            Cancel
                        </LemonButton>
                    )}
                    <LemonButton
                        type="primary"
                        onClick={() => handleSubmit()}
                        loading={messageSending}
                        disabledReason={sendBlockedReason}
                        sideAction={
                            !isEditing && sendAndSetStatusOptions?.length
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
                        {isEditing ? (
                            'Save'
                        ) : isPrivate ? (
                            'Attach'
                        ) : showChannelLogo ? (
                            <span className="inline-flex items-center gap-1.5">
                                {buttonText}
                                <span className="text-sm dark:grayscale">{channelIcon[channel]}</span>
                            </span>
                        ) : (
                            buttonText
                        )}
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
