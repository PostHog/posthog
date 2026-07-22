import { JSONContent } from '@tiptap/core'
import { useEffect, useRef, useState } from 'react'

import { IconLock } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSwitch, Tooltip } from '@posthog/lemon-ui'
import type { LemonSegmentedButtonOption } from '@posthog/lemon-ui'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import type { TicketStatus } from '../../types'
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
    buttonText?: string
    minRows?: number
    /** Whether to show the reply / internal-note tab switch */
    showPrivateOption?: boolean
    /** Public reply draft content to restore (from parent logic for tab persistence) */
    draftContent?: JSONContent | null
    /** Called when the public reply draft changes */
    onDraftChange?: (content: JSONContent | null) => void
    /** Internal-note draft content, kept separate from the public reply so the two
     *  tabs never overwrite each other. Only used when showPrivateOption is set. */
    privateDraftContent?: JSONContent | null
    /** Called when the internal-note draft changes */
    onPrivateDraftChange?: (content: JSONContent | null) => void
    /** Whether the internal-note tab is the active one (from parent logic for tab persistence) */
    isPrivate?: boolean
    /** Called when the active tab changes */
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
    placeholder = 'Type your message...',
    buttonText = 'Send',
    minRows = 3,
    showPrivateOption = false,
    draftContent,
    onDraftChange,
    privateDraftContent,
    onPrivateDraftChange,
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
    const [isUploading, setIsUploading] = useState(false)
    const [localIsPrivate, setLocalIsPrivate] = useState(false)
    const editorRef = useRef<RichContentEditorType | null>(null)

    // Support controlled or uncontrolled active-tab state
    const isPrivate = controlledIsPrivate ?? localIsPrivate
    const setIsPrivate = onPrivateChange ?? setLocalIsPrivate

    // The editor only ever holds the active tab's body; the other tab's body lives
    // in the parent (draftContent / privateDraftContent) and is swapped into the
    // editor on a tab change so the reply and the internal note never overwrite
    // each other.
    const activeDraftContent = isPrivate ? privateDraftContent : draftContent

    const [isEmpty, setIsEmpty] = useState(!activeDraftContent)

    // Keep isEmpty aligned with the active buffer — covers both external draft
    // updates and tab switches (which change which buffer is active).
    useEffect(() => {
        setIsEmpty(!activeDraftContent)
    }, [activeDraftContent])

    const sendVerb = isPrivate ? 'Attach' : 'Send'

    // Empty doc mirrors SupportEditor's default so setContent clears the editor cleanly.
    const EMPTY_DOC: JSONContent = { type: 'doc', content: [{ type: 'paragraph' }] }

    const handleTabChange = (nextIsPrivate: boolean): void => {
        if (nextIsPrivate === isPrivate) {
            return
        }
        const editor = editorRef.current
        if (editor) {
            // Stash whatever is in the editor into the outgoing tab's buffer, then
            // load the incoming tab's buffer (empty doc when it has no draft yet).
            const current = editor.isEmpty?.() ? null : editor.getJSON()
            if (isPrivate) {
                onPrivateDraftChange?.(current)
            } else {
                onDraftChange?.(current)
            }
            const incoming = nextIsPrivate ? privateDraftContent : draftContent
            editor.setContent?.(incoming ?? EMPTY_DOC)
            setIsEmpty(!incoming)
            editor.focus?.()
        }
        setIsPrivate(nextIsPrivate)
    }

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
                        // Clear only the tab that was just sent; the other tab's draft
                        // is deliberately preserved so sending a reply never discards an
                        // in-progress internal note (or vice versa), and the active tab
                        // stays put.
                        editorRef.current?.clear()
                        setIsEmpty(true)
                        if (isPrivate) {
                            onPrivateDraftChange?.(null)
                        } else {
                            onDraftChange?.(null)
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
        if (!editorRef.current) {
            return
        }
        // Route edits to the active tab's buffer so each tab keeps its own body.
        const json = empty ? null : editorRef.current.getJSON()
        if (isPrivate) {
            onPrivateDraftChange?.(json)
        } else {
            onDraftChange?.(json)
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

    // A dot on the inactive tab flags an in-progress draft there, so the other
    // buffer stays discoverable. The active tab's content is visible, so no dot.
    const publicHasDraft = isPrivate ? !!draftContent : !isEmpty
    const privateHasDraft = isPrivate ? !isEmpty : !!privateDraftContent
    const draftDot = <span className="w-1.5 h-1.5 rounded-full bg-accent" aria-hidden />
    const tabOptions: LemonSegmentedButtonOption<'reply' | 'note'>[] = [
        {
            value: 'reply',
            label: (
                <span className="inline-flex items-center gap-1.5">
                    Reply
                    {isPrivate && publicHasDraft ? draftDot : null}
                </span>
            ),
        },
        {
            value: 'note',
            tooltip: 'Private notes are only visible to your team, not to the customer.',
            label: (
                <span className="inline-flex items-center gap-1.5">
                    <IconLock className="text-sm" />
                    Internal note
                    {!isPrivate && privateHasDraft ? draftDot : null}
                </span>
            ),
        },
    ]

    return (
        <div>
            <SupportEditor
                initialContent={activeDraftContent}
                placeholder={placeholder}
                onCreate={(editor) => {
                    editorRef.current = editor
                    if (activeDraftContent) {
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
                    <LemonSegmentedButton
                        size="small"
                        value={isPrivate ? 'note' : 'reply'}
                        onChange={(value) => handleTabChange(value === 'note')}
                        options={tabOptions}
                    />
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
