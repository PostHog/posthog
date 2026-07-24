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
    draftContent?: JSONContent | null
    /** Called when draft content changes */
    onDraftChange?: (content: JSONContent | null) => void
    /** Content to append into the live editor once; cleared via onInsertConsumed after it's applied */
    pendingInsert?: JSONContent | null
    /** Called after pendingInsert has been inserted */
    onInsertConsumed?: () => void
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
    pendingInsert,
    onInsertConsumed,
    isPrivate: controlledIsPrivate,
    onPrivateChange,
    extraActions,
    replyDisabledReason,
    draftMode = false,
    onDraftModeChange,
    sendConfirmationMessage,
    sendAndSetStatusOptions,
    unsavedTicketChanges,
}: MessageInputProps): JSX.Element {
    const [isEmpty, setIsEmpty] = useState(!draftContent)
    const [isUploading, setIsUploading] = useState(false)
    const [localIsPrivate, setLocalIsPrivate] = useState(false)
    const [editorReady, setEditorReady] = useState(false)
    const editorRef = useRef<RichContentEditorType | null>(null)

    useEffect(() => {
        setIsEmpty(!draftContent)
    }, [draftContent])

    // Append externally-provided content (e.g. a generated merch-code message) to the end of the
    // live editor, then signal the parent to clear it. The editor's own onUpdate syncs the draft.
    // Gated on editorReady so a value that arrives before the editor mounts isn't stranded — the
    // effect re-runs once onCreate flips editorReady.
    useEffect(() => {
        if (pendingInsert && editorReady && editorRef.current) {
            editorRef.current.insertContentAt(editorRef.current.getEndPosition(), pendingInsert)
            editorRef.current.focus()
            setIsEmpty(false)
            onInsertConsumed?.()
        }
    }, [pendingInsert, editorReady, onInsertConsumed])

    // Support controlled or uncontrolled isPrivate
    const isPrivate = controlledIsPrivate ?? localIsPrivate
    const setIsPrivate = onPrivateChange ?? setLocalIsPrivate

    const resolvedPlaceholder = placeholder ?? (isPrivate ? 'Type your private note...' : getReplyPlaceholder(channel))
    const showChannelLogo = !isPrivate && hasReplyChannelBranding(channel)
    const sendVerb = isPrivate ? 'Attach' : 'Send'

    const handleSubmit = (statusAfterSend?: TicketStatus): void => {
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
                    statusAfterSend
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
                : undefined

    return (
        <div>
            <SupportEditor
                initialContent={draftContent}
                placeholder={resolvedPlaceholder}
                onCreate={(editor) => {
                    editorRef.current = editor
                    setEditorReady(true)
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
                        {isPrivate ? (
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
