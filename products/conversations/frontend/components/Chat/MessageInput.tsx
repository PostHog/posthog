import { JSONContent } from '@tiptap/core'
import { useEffect, useId, useRef, useState } from 'react'

import { IconLock } from '@posthog/icons'

import { RichContentEditorType } from 'lib/components/RichContentEditor/types'
import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    ButtonGroup,
    Checkbox,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Input,
    Label,
    SelectTriggerIcon,
    Switch,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'

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
    /** Show a one-line field until focused, then the full composer. */
    collapseUntilActive?: boolean
    /** When this changes, the collapsed composer closes. Ticket navigation reuses the same mount. */
    threadId?: string
}

type PendingConfirm =
    | { kind: 'unsaved'; statusAfterSend: TicketStatus }
    | { kind: 'draft'; statusAfterSend?: TicketStatus }

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
    collapseUntilActive = false,
    threadId,
}: MessageInputProps): JSX.Element {
    const [isEmpty, setIsEmpty] = useState(!draftContent)
    const [isUploading, setIsUploading] = useState(false)
    const [localIsPrivate, setLocalIsPrivate] = useState(false)
    const [composerExpanded, setComposerExpanded] = useState(false)
    const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null)
    const lastThreadIdRef = useRef(threadId)
    if (lastThreadIdRef.current !== threadId) {
        lastThreadIdRef.current = threadId
        setComposerExpanded(false)
    }
    const editorRef = useRef<RichContentEditorType | null>(null)
    const lastSeededEditId = useRef<string | null>(null)
    const draftContentRef = useRef(draftContent)
    draftContentRef.current = draftContent
    const isEditing = !!editingMessageId
    const privateNoteId = useId()
    const draftModeId = useId()

    useEffect(() => {
        setIsEmpty(!draftContent)
    }, [draftContent])

    useEffect(() => {
        if (composerExpanded) {
            editorRef.current?.focus()
        }
    }, [composerExpanded])

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

    const performSend = (statusAfterSend?: TicketStatus): void => {
        if (!editorRef.current || isEmpty) {
            return
        }
        const richContent = editorRef.current.getJSON()
        const content = serializeToMarkdown(richContent)
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

    const handleSubmit = (statusAfterSend?: TicketStatus): void => {
        // These guard the Cmd+Enter path, which bypasses the disabled button.
        if (sendDisabledReason || (replyDisabledReason && !isPrivate && !isEditing)) {
            return
        }
        if (messageSending || isUploading) {
            return
        }
        if (!editorRef.current || isEmpty) {
            return
        }
        // Sending with a status saves the whole ticket, so surface any other unsaved edits first.
        if (!isEditing && statusAfterSend && unsavedTicketChanges && unsavedTicketChanges.length > 0) {
            setPendingConfirm({ kind: 'unsaved', statusAfterSend })
            return
        }
        if (!isEditing && draftMode && !isPrivate && sendConfirmationMessage) {
            // Private notes are never sent externally, so they skip the draft-mode confirmation.
            setPendingConfirm({ kind: 'draft', statusAfterSend })
            return
        }
        performSend(statusAfterSend)
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
    const sendDisabled = !!sendBlockedReason || messageSending
    const privateNoteDisabled = isEditing || !!sendControlDisabledReason
    const privateNoteDisabledReason = isEditing ? 'Editing a private note' : sendControlDisabledReason
    const draftModeDisabledReason =
        sendControlDisabledReason ?? (isPrivate || isEditing ? 'Draft mode has no effect on private notes' : undefined)

    const sendLabel = isEditing ? (
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
    )

    const sendButton = (
        <Button variant="primary" onClick={() => handleSubmit()} loading={messageSending} disabled={sendDisabled}>
            {sendLabel}
        </Button>
    )

    const sendControls =
        !isEditing && sendAndSetStatusOptions?.length ? (
            <ButtonGroup>
                {sendButton}
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="primary"
                                disabled={sendDisabled}
                                aria-label={`${sendVerb} and set ticket status`}
                            />
                        }
                    >
                        <SelectTriggerIcon />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        {sendAndSetStatusOptions.map((option) => (
                            <DropdownMenuItem key={option.value} onClick={() => handleSubmit(option.value)}>
                                {`${sendVerb} and set ${option.statusLabel}`}
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                </DropdownMenu>
            </ButtonGroup>
        ) : (
            sendButton
        )

    const showFullComposer = !collapseUntilActive || composerExpanded || !!draftContent || !!editingMessageId

    if (!showFullComposer) {
        return (
            <Input
                className="w-full"
                value=""
                placeholder={getReplyPlaceholder(channel)}
                disabled={!!sendControlDisabledReason}
                title={sendControlDisabledReason}
                onChange={() => setComposerExpanded(true)}
                onFocus={() => setComposerExpanded(true)}
                data-attr="message-input-collapsed"
            />
        )
    }

    return (
        <div>
            <SupportEditor
                initialContent={typeof draftContent === 'string' ? null : draftContent}
                placeholder={resolvedPlaceholder}
                autoFocus={composerExpanded}
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
                    <Tooltip>
                        <TooltipTrigger render={<span className="inline-flex items-center gap-2" />}>
                            <Checkbox
                                id={privateNoteId}
                                checked={isPrivate || isEditing}
                                onCheckedChange={(checked) => setIsPrivate(!!checked)}
                                disabled={privateNoteDisabled}
                                title={privateNoteDisabledReason}
                            />
                            <Label htmlFor={privateNoteId} className="inline-flex items-center gap-1 font-normal">
                                <IconLock className="text-sm" />
                                {isEditing ? 'Editing private note' : 'Attach as private note'}
                            </Label>
                        </TooltipTrigger>
                        <TooltipContent>
                            Private notes are only visible to your team, not to the customer.
                        </TooltipContent>
                    </Tooltip>
                ) : (
                    <div />
                )}
                <div className="flex items-center gap-2">
                    {onDraftModeChange &&
                        (isPrivate || isEditing ? (
                            <span className="inline-flex items-center gap-2">
                                <Switch
                                    id={draftModeId}
                                    checked={draftMode}
                                    onCheckedChange={(checked) => onDraftModeChange(!!checked)}
                                    disabled={!!draftModeDisabledReason}
                                    title={draftModeDisabledReason}
                                />
                                <Label htmlFor={draftModeId} className="font-normal">
                                    Draft mode
                                </Label>
                            </span>
                        ) : (
                            <Tooltip>
                                <TooltipTrigger render={<span className="inline-flex items-center gap-2" />}>
                                    <Switch
                                        id={draftModeId}
                                        checked={draftMode}
                                        onCheckedChange={(checked) => onDraftModeChange(!!checked)}
                                        disabled={!!draftModeDisabledReason}
                                        title={draftModeDisabledReason}
                                    />
                                    <Label htmlFor={draftModeId} className="font-normal">
                                        Draft mode
                                    </Label>
                                </TooltipTrigger>
                                <TooltipContent>
                                    In draft mode, sending asks you to confirm the recipient first.
                                </TooltipContent>
                            </Tooltip>
                        ))}
                    {extraActions}
                    {isEditing && onCancelEdit && (
                        <Button variant="outline" onClick={onCancelEdit} disabled={messageSending}>
                            Cancel
                        </Button>
                    )}
                    {sendBlockedReason ? (
                        <Tooltip>
                            <TooltipTrigger render={<span className="inline-flex" />}>{sendControls}</TooltipTrigger>
                            <TooltipContent>{sendBlockedReason}</TooltipContent>
                        </Tooltip>
                    ) : (
                        sendControls
                    )}
                </div>
            </div>
            <AlertDialog open={pendingConfirm !== null} onOpenChange={(open) => !open && setPendingConfirm(null)}>
                {pendingConfirm?.kind === 'unsaved' ? (
                    <AlertDialogContent>
                        <AlertDialogHeader>
                            <AlertDialogTitle>{`${sendVerb} and save other changes?`}</AlertDialogTitle>
                            <AlertDialogDescription render={<div />}>
                                <p>
                                    {isPrivate ? 'Attaching' : 'Sending'} will also save your other unsaved ticket
                                    changes:
                                </p>
                                <ul className="list-disc pl-5">
                                    {unsavedTicketChanges?.map((change) => (
                                        <li key={change}>{change}</li>
                                    ))}
                                </ul>
                                {draftMode && !isPrivate && sendConfirmationMessage ? (
                                    <p>{sendConfirmationMessage}</p>
                                ) : null}
                            </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                            <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                            <AlertDialogClose
                                render={
                                    <Button
                                        variant="primary"
                                        onClick={() => performSend(pendingConfirm.statusAfterSend)}
                                    />
                                }
                            >
                                {`${sendVerb} and save`}
                            </AlertDialogClose>
                        </AlertDialogFooter>
                    </AlertDialogContent>
                ) : pendingConfirm?.kind === 'draft' ? (
                    <AlertDialogContent>
                        <AlertDialogHeader>
                            <AlertDialogTitle>Ready to send?</AlertDialogTitle>
                            <AlertDialogDescription>{sendConfirmationMessage}</AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                            <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                            <AlertDialogClose
                                render={
                                    <Button
                                        variant="primary"
                                        onClick={() => performSend(pendingConfirm.statusAfterSend)}
                                    />
                                }
                            >
                                Send
                            </AlertDialogClose>
                        </AlertDialogFooter>
                    </AlertDialogContent>
                ) : null}
            </AlertDialog>
        </div>
    )
}
