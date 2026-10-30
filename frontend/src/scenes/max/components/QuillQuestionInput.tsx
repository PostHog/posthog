import { offset } from '@floating-ui/react'
import { BindLogic, useActions, useValues } from 'kea'
import React, { ReactNode, useEffect, useRef, useState } from 'react'

import { IconArrowRight, IconCheck, IconPencil, IconPlus, IconStopFilled, IconTrash, IconX } from '@posthog/icons'
import { LemonTextArea } from '@posthog/lemon-ui'
import { Button, Spinner, Switch, Text } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { QuillComposerLayout } from 'products/posthog_ai/frontend/api/composer'

import { ContextTags, ContextToolInfoTags, SandboxContextTags } from '../Context'
import { maxThreadLogic } from '../maxThreadLogic'
import { posthogAiContextLogic } from '../posthogAiContextLogic'
import {
    QUEUED_MESSAGES_HEADING,
    RESEARCH_BETA_NOTICE,
    SUPPORT_OVERRIDE_LABEL,
    SUPPORT_SESSION_NOTICE,
    composerPlaceholder,
} from './composerCopy'
import { FillInHint } from './FillInHint'
import { QuillContextPicker } from './QuillContextPicker'
import { QuillModeSelector } from './QuillModeSelector'
import { SlashCommandAutocomplete } from './SlashCommandAutocomplete'
import { type QueuedMessageEditProps, useQuestionInput } from './useQuestionInput'

interface QuillQuestionInputProps {
    isSticky?: boolean
    placeholder?: string
    children?: ReactNode
    isThreadVisible?: boolean
    textAreaRef?: React.RefObject<HTMLTextAreaElement>
    containerClassName?: string
    onSubmit?: () => void
}

function QuillQueuedMessageItem({ message, isEditing, onEdit, onCancel, onSave }: QueuedMessageEditProps): JSX.Element {
    const { deleteQueuedMessage } = useActions(maxThreadLogic)
    const [draft, setDraft] = useState(message.content)
    const textAreaRef = useRef<HTMLTextAreaElement | null>(null)

    useEffect(() => {
        setDraft(message.content)
    }, [message.content])

    useEffect(() => {
        if (isEditing) {
            textAreaRef.current?.focus()
            textAreaRef.current?.select()
        }
    }, [isEditing])

    const canSave = draft.trim().length > 0

    if (isEditing) {
        return (
            <div className="flex flex-col gap-2">
                <LemonTextArea
                    ref={textAreaRef}
                    value={draft}
                    onChange={setDraft}
                    minRows={1}
                    maxRows={4}
                    autoFocus
                    onPressCmdEnter={() => {
                        if (!canSave) {
                            return
                        }
                        onSave(message.id, draft)
                    }}
                />
                <div className="flex gap-1">
                    <Button
                        size="sm"
                        variant="primary"
                        onClick={() => onSave(message.id, draft)}
                        disabledReason={canSave ? undefined : 'Message cannot be empty'}
                    >
                        <IconCheck />
                        Save
                    </Button>
                    <Button size="sm" variant="outline" onClick={onCancel}>
                        <IconX />
                        Cancel
                    </Button>
                </div>
            </div>
        )
    }

    return (
        <div className="group flex items-center gap-2 rounded-md px-2 py-1 hover:bg-fill-hover">
            <Text size="xs" variant="muted" className="m-0 flex-1 truncate">
                {message.content}
            </Text>
            <div className="flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                <Button
                    size="icon-xs"
                    variant="default"
                    aria-label="Edit message"
                    tooltip="Edit message"
                    onClick={onEdit}
                >
                    <IconPencil />
                </Button>
                <Button
                    size="icon-xs"
                    variant="default"
                    aria-label="Remove from queue"
                    tooltip="Remove from queue"
                    onClick={() => deleteQueuedMessage(message.id)}
                >
                    <IconTrash />
                </Button>
            </div>
        </div>
    )
}

/** The context chips of the legacy composer, as the lemon composer draws them; the pickers moved to the quill controls row. */
function QuillContextChips(): JSX.Element | null {
    const { showContextUI, conversation, sandboxConversationKey } = useValues(maxThreadLogic)
    if (!showContextUI) {
        return null
    }
    if (conversation?.agent_runtime === 'sandbox') {
        return sandboxConversationKey ? (
            <BindLogic logic={posthogAiContextLogic} props={{ conversationId: sandboxConversationKey }}>
                <SandboxContextTags />
            </BindLogic>
        ) : null
    }
    return (
        <>
            <ContextToolInfoTags />
            <ContextTags />
        </>
    )
}

/**
 * The legacy PostHog AI composer in the quill skin, drawn like the sandbox runner's composer: one bordered
 * input group with an inline send button and a controls row beneath. Behavior comes from `useQuestionInput`,
 * which the lemon `QuestionInput` shares.
 */
export const QuillQuestionInput = React.forwardRef<HTMLDivElement, QuillQuestionInputProps>(function QuillQuestionInput(
    { isSticky, placeholder, children, isThreadVisible, textAreaRef, containerClassName, onSubmit },
    ref
) {
    const groupRef = useRef<HTMLDivElement>(null)
    const internalTextAreaRef = useRef<HTMLTextAreaElement>(null)
    const resolvedTextAreaRef = textAreaRef ?? internalTextAreaRef
    const { showContextUI } = useValues(maxThreadLogic)
    const {
        inputValue,
        handleQuestionChange,
        fillInHint,
        showFillInHint,
        promptLength,
        isOverLengthLimit,
        maxMessageLength,
        conversation,
        threadLoading,
        inputDisabled,
        isSharedThread,
        pendingPrompt,
        dataProcessingAccepted,
        showResearchBanner,
        showAttachButton,
        attachmentInputRef,
        handleAttachmentChange,
        queueingEnabled,
        displayQueuedMessages,
        queuedMessages,
        queueSubmitting,
        editingQueueId,
        setEditingQueueId,
        saveQueuedMessage,
        isQueueingSubmission,
        showStopButton,
        disabledReason,
        slashCommandIcon,
        submit,
        handleSendClick,
        handlePressEnter,
        handleKeyDown,
        handleBlur,
        completeThreadGeneration,
        showAutocomplete,
        closeAutocomplete,
        isImpersonatedInternalConversation,
        isImpersonatingExistingConversation,
        supportOverrideEnabled,
        setSupportOverrideEnabled,
    } = useQuestionInput({ textAreaRef: resolvedTextAreaRef, onSubmit })

    const placeholderCopy = composerPlaceholder({
        conversation,
        isSharedThread,
        threadLoading,
        isThreadVisible,
        placeholder,
    })
    const placeholderText =
        placeholderCopy.kind === 'prompt' ? `${placeholderCopy.lead}, ${placeholderCopy.hint}` : placeholderCopy.text

    const sendLabel = showStopButton ? 'Stop' : isQueueingSubmission ? 'Queue message' : 'Send message'
    const sendButton = showStopButton ? (
        <Button
            type="button"
            variant="destructive"
            size="icon"
            aria-label="Stop"
            tooltip={disabledReason ?? 'Stop'}
            onClick={handleSendClick}
            data-attr="max-stop-generation"
        >
            <IconStopFilled />
        </Button>
    ) : (
        <Button
            type="button"
            variant="primary"
            size="icon"
            // Looks disabled like the sandbox send button, but stays clickable (see below).
            className={cn('rounded-xs', disabledReason && 'opacity-50')}
            aria-label={sendLabel}
            tooltip={disabledReason ?? sendLabel}
            loading={threadLoading && !dataProcessingAccepted}
            // The button stays clickable while disabled: the click puts focus back in the field.
            aria-disabled={!!disabledReason}
            onClick={handleSendClick}
            data-attr="max-send-message"
        >
            {slashCommandIcon ?? <IconArrowRight className="-rotate-90" />}
        </Button>
    )

    return (
        <div
            ref={ref}
            data-quill
            className={cn(
                'w-full px-3',
                (isSticky || isThreadVisible) && 'sticky bottom-0 z-10 max-w-180 self-center',
                // containerClassName last so callers can override (e.g. sidePanel's px-0).
                containerClassName
            )}
        >
            <div className="relative z-1 flex w-full flex-col gap-2">
                {children}
                {showResearchBanner && (
                    <Text
                        size="xs"
                        className="m-0 rounded-lg bg-warning px-2 py-1.5 text-center text-warning-foreground"
                    >
                        {RESEARCH_BETA_NOTICE}
                    </Text>
                )}
                {queueingEnabled && (queuedMessages.length > 0 || queueSubmitting) && (
                    <div className="flex flex-col gap-1 px-1">
                        <Text size="xs" variant="muted" className="m-0 flex items-center gap-1.5">
                            {QUEUED_MESSAGES_HEADING}
                            {queueSubmitting && <Spinner />}
                        </Text>
                        {displayQueuedMessages.map((message) => (
                            <QuillQueuedMessageItem
                                key={message.id}
                                message={message}
                                isEditing={editingQueueId === message.id}
                                onEdit={() => setEditingQueueId(message.id)}
                                onCancel={() => setEditingQueueId(null)}
                                onSave={saveQueuedMessage}
                            />
                        ))}
                    </div>
                )}
                <SlashCommandAutocomplete visible={showAutocomplete} onClose={closeAutocomplete}>
                    <div className="w-full">
                        <QuillComposerLayout
                            groupRef={groupRef}
                            textAreaRef={resolvedTextAreaRef}
                            // No wrapper element, so the chip row stays empty and hides itself when there are no chips.
                            chips={!isSharedThread && showContextUI ? <QuillContextChips /> : undefined}
                            field={
                                <>
                                    {!inputValue && (
                                        <div
                                            data-slot="composer-placeholder"
                                            id="question-input-hint"
                                            className="pointer-events-none absolute text-sm text-muted-foreground"
                                        >
                                            {placeholderText}
                                        </div>
                                    )}
                                    {/* Postfix cue after a fill-in suggestion's typed-in prefix. */}
                                    {showFillInHint && fillInHint && (
                                        <div className="pointer-events-none absolute inset-x-0 top-2 overflow-hidden">
                                            <FillInHint text={inputValue} hint={fillInHint} />
                                        </div>
                                    )}
                                    <LemonTextArea
                                        aria-describedby={!inputValue ? 'question-input-hint' : undefined}
                                        id="question-input"
                                        data-attr="max-chat-input"
                                        ref={resolvedTextAreaRef}
                                        value={isSharedThread ? '' : inputValue}
                                        onChange={handleQuestionChange}
                                        onBlur={handleBlur}
                                        onPressEnter={handlePressEnter}
                                        onKeyDown={handleKeyDown}
                                        disabled={inputDisabled}
                                        minRows={1}
                                        maxRows={10}
                                        className={cn(
                                            '!border-none !bg-transparent py-2 pl-2 resize-none',
                                            // Hide the native caret so only the enlarged fill-in caret shows.
                                            showFillInHint && 'caret-transparent'
                                        )}
                                        hideFocus
                                    />
                                </>
                            }
                            send={
                                isSharedThread ? (
                                    <></>
                                ) : (
                                    <AIConsentPopoverWrapper
                                        placement="bottom-end"
                                        showArrow
                                        ignoreDismissal
                                        onApprove={() => submit(pendingPrompt || inputValue)}
                                        onDismiss={() => completeThreadGeneration()}
                                        middleware={[
                                            offset((state) => ({
                                                mainAxis: state.placement.includes('top') ? 30 : 1,
                                            })),
                                        ]}
                                        hidden={!threadLoading && !pendingPrompt}
                                    >
                                        {/* The consent popover anchors to a plain element, as the sandbox send button does. */}
                                        <span className="flex">{sendButton}</span>
                                    </AIConsentPopoverWrapper>
                                )
                            }
                            controls={
                                !isSharedThread && showContextUI ? (
                                    <>
                                        {showAttachButton && (
                                            <>
                                                <input
                                                    ref={attachmentInputRef}
                                                    type="file"
                                                    multiple
                                                    className="hidden"
                                                    data-attr="max-new-chat-attach-input"
                                                    onChange={handleAttachmentChange}
                                                />
                                                <Button
                                                    size="icon-sm"
                                                    variant="default"
                                                    aria-label="Attach files"
                                                    tooltip="Attach files in new PostHog AI. Your draft moves with you."
                                                    onClick={() => attachmentInputRef.current?.click()}
                                                    data-attr="max-new-chat-attach-file"
                                                >
                                                    <IconPlus />
                                                </Button>
                                            </>
                                        )}
                                        <QuillContextPicker />
                                        <QuillModeSelector />
                                    </>
                                ) : undefined
                            }
                            meta={
                                promptLength !== null ? (
                                    <Text
                                        size="xs"
                                        variant={isOverLengthLimit ? 'destructive' : 'muted'}
                                        className="m-0"
                                    >
                                        {promptLength.toLocaleString()} / {maxMessageLength.toLocaleString()}
                                    </Text>
                                ) : undefined
                            }
                        />
                    </div>
                </SlashCommandAutocomplete>
                {/* Info banner for conversations created during impersonation (marked as internal) */}
                {isImpersonatedInternalConversation && (
                    <Text size="xs" variant="muted" className="m-0 px-2">
                        {SUPPORT_SESSION_NOTICE}
                    </Text>
                )}
                {/* Override switch - shown when impersonating and viewing an existing customer conversation (not internal) */}
                {!conversation?.is_internal && (isImpersonatingExistingConversation || supportOverrideEnabled) && (
                    <label className="flex items-center gap-2 rounded-lg bg-warning px-2 py-1 text-warning-foreground">
                        <Switch
                            checked={supportOverrideEnabled}
                            onCheckedChange={(checked: boolean) => setSupportOverrideEnabled(checked)}
                            aria-label={SUPPORT_OVERRIDE_LABEL}
                        />
                        <Text size="xs" className="m-0">
                            {SUPPORT_OVERRIDE_LABEL}
                        </Text>
                    </label>
                )}
            </div>
        </div>
    )
})
