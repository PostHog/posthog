import './QuestionInput.scss'

import { offset } from '@floating-ui/react'
import { useActions } from 'kea'
import React, { ReactNode, useEffect, useRef, useState } from 'react'

import { IconArrowRight, IconCheck, IconPencil, IconStopFilled, IconTrash, IconUpload, IconX } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { cn } from 'lib/utils/css-classes'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { ContextDisplay } from '../Context'
import { maxThreadLogic } from '../maxThreadLogic'
import {
    QUEUED_MESSAGES_HEADING,
    RESEARCH_BETA_NOTICE,
    SUPPORT_OVERRIDE_LABEL,
    SUPPORT_SESSION_NOTICE,
    composerPlaceholder,
} from './composerCopy'
import { FillInHint } from './FillInHint'
import { SlashCommandAutocomplete } from './SlashCommandAutocomplete'
import { type QueuedMessageEditProps, useQuestionInput } from './useQuestionInput'

interface QuestionInputProps {
    isSticky?: boolean
    placeholder?: string
    children?: ReactNode
    contextDisplaySize?: 'small' | 'default'
    isThreadVisible?: boolean
    topActions?: ReactNode
    bottomActions?: ReactNode
    textAreaRef?: React.RefObject<HTMLTextAreaElement>
    containerClassName?: string
    onSubmit?: () => void
}

function QueuedMessageItem({ message, isEditing, onEdit, onCancel, onSave }: QueuedMessageEditProps): JSX.Element {
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
            <div className="space-y-2">
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
                    <LemonButton
                        size="xsmall"
                        icon={<IconCheck />}
                        onClick={() => onSave(message.id, draft)}
                        disabledReason={canSave ? undefined : 'Message cannot be empty'}
                    >
                        Save
                    </LemonButton>
                    <LemonButton size="xsmall" type="secondary" icon={<IconX />} onClick={onCancel}>
                        Cancel
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <div className="group flex items-center gap-2 py-1 px-2 rounded-md hover:bg-bg-light">
            <p className="flex-1 text-sm text-secondary truncate mb-0">{message.content}</p>
            <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconPencil className="text-muted" />}
                    onClick={onEdit}
                    tooltip="Edit message"
                />
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconTrash className="text-muted" />}
                    onClick={() => {
                        deleteQueuedMessage(message.id)
                    }}
                    tooltip="Remove from queue"
                />
            </div>
        </div>
    )
}

export const QuestionInput = React.forwardRef<HTMLDivElement, QuestionInputProps>(function BaseQuestionInput(
    {
        isSticky,
        placeholder,
        children,
        contextDisplaySize,
        isThreadVisible,
        topActions,
        textAreaRef,
        containerClassName,
        onSubmit,
    },
    ref
) {
    const {
        inputValue,
        handleQuestionChange,
        hasQuestion,
        fillInHint,
        showFillInHint,
        promptLength,
        isOverLengthLimit,
        maxMessageLength,
        conversation,
        threadLoading,
        inputDisabled,
        isSharedThread,
        streamingActive,
        pendingPrompt,
        dataProcessingAccepted,
        showResearchBanner,
        showAttachButton,
        attachmentInputRef,
        handleAttachmentChange,
        queueingEnabled,
        queuedMessages,
        displayQueuedMessages,
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
    } = useQuestionInput({ textAreaRef, onSubmit })
    const placeholderCopy = composerPlaceholder({
        conversation,
        isSharedThread,
        threadLoading,
        isThreadVisible,
        placeholder,
    })

    return (
        <div
            className={cn(
                'w-full px-3',
                (isSticky || isThreadVisible) && 'sticky bottom-0 z-10 max-w-180 self-center',
                // containerClassName last so callers can override (e.g. sidePanel's px-0).
                containerClassName
            )}
            ref={ref}
        >
            <div
                className={cn(
                    'flex flex-col items-center',
                    isSticky && 'border border-primary rounded-lg backdrop-blur-sm bg-glass-bg-3000'
                )}
            >
                {/* Have to increase z-index to overlay ToolsDisplay */}
                <div className="relative w-full flex flex-col z-1">
                    {children}
                    {showResearchBanner && (
                        <div className="flex justify-center items-center gap-1 w-full px-2 py-1.5 mb-2 bg-warning/10 text-primary text-xs rounded-lg border-primary">
                            {RESEARCH_BETA_NOTICE}
                        </div>
                    )}
                    {queueingEnabled && (queuedMessages.length > 0 || queueSubmitting) && (
                        <div className="px-3 py-2">
                            <div className="text-xs text-muted mb-1.5 flex items-center gap-1.5">
                                {QUEUED_MESSAGES_HEADING}
                                {queueSubmitting && <Spinner size="small" />}
                            </div>
                            <div className="space-y-1.5">
                                {displayQueuedMessages.map((message) => (
                                    <QueuedMessageItem
                                        key={message.id}
                                        message={message}
                                        isEditing={editingQueueId === message.id}
                                        onEdit={() => {
                                            setEditingQueueId(message.id)
                                        }}
                                        onCancel={() => {
                                            setEditingQueueId(null)
                                        }}
                                        onSave={saveQueuedMessage}
                                    />
                                ))}
                            </div>
                        </div>
                    )}
                    <label
                        htmlFor="question-input"
                        className={cn(
                            'input-like flex flex-col cursor-text',
                            'border border-primary',
                            'bg-[var(--color-bg-fill-input)]',
                            isThreadVisible ? 'border-primary m-0.5 rounded-[7px]' : 'rounded-lg',
                            '[--input-ring-size:2px]',
                            !streamingActive && '[--input-ring-color:var(--color-ai)]'
                        )}
                    >
                        <SlashCommandAutocomplete visible={showAutocomplete} onClose={closeAutocomplete}>
                            <div className="relative w-full">
                                {!inputValue && (
                                    <div
                                        id="textarea-hint"
                                        className="text-secondary absolute top-4 left-4 text-sm pointer-events-none"
                                    >
                                        {placeholderCopy.kind === 'prompt' ? (
                                            <>
                                                {placeholderCopy.lead}{' '}
                                                <span className="text-tertiary opacity-80 contrast-more:opacity-100">
                                                    {placeholderCopy.hint}
                                                </span>
                                            </>
                                        ) : (
                                            placeholderCopy.text
                                        )}
                                    </div>
                                )}
                                {/* Postfix cue after a fill-in suggestion's typed-in prefix. */}
                                {showFillInHint && (
                                    <div className="absolute top-4 left-4 right-4 overflow-hidden pointer-events-none">
                                        <FillInHint text={inputValue} hint={fillInHint ?? ''} />
                                    </div>
                                )}
                                <LemonTextArea
                                    aria-describedby={!inputValue ? 'textarea-hint' : undefined}
                                    id="question-input"
                                    data-attr="max-chat-input"
                                    ref={textAreaRef}
                                    value={isSharedThread ? '' : inputValue}
                                    onChange={handleQuestionChange}
                                    onBlur={handleBlur}
                                    onPressEnter={handlePressEnter}
                                    onKeyDown={handleKeyDown}
                                    disabled={inputDisabled}
                                    minRows={1}
                                    maxRows={10}
                                    className={cn(
                                        '!border-none !bg-transparent min-h-16 py-2 pl-2 resize-none',
                                        'pr-12',
                                        // Hide the native caret so only the enlarged fill-in caret shows.
                                        showFillInHint && 'caret-transparent'
                                    )}
                                    hideFocus
                                />
                            </div>
                        </SlashCommandAutocomplete>

                        {!isSharedThread && (
                            <div className="pb-2 pr-12">
                                {!isThreadVisible ? (
                                    <div className="flex justify-between items-start">
                                        <div className="flex items-start gap-1 flex-1 min-w-0">
                                            <div className="flex-1 min-w-0">
                                                <ContextDisplay size={contextDisplaySize} />
                                            </div>
                                            {showAttachButton && (
                                                <div className="shrink-0">
                                                    <input
                                                        ref={attachmentInputRef}
                                                        type="file"
                                                        multiple
                                                        className="hidden"
                                                        data-attr="max-new-chat-attach-input"
                                                        onChange={handleAttachmentChange}
                                                    />
                                                    <LemonButton
                                                        size="xxsmall"
                                                        type="tertiary"
                                                        className="border"
                                                        icon={<IconUpload />}
                                                        tooltip="Attach files in new PostHog AI. Your draft moves with you."
                                                        onClick={() => attachmentInputRef.current?.click()}
                                                        data-attr="max-new-chat-attach-file"
                                                    >
                                                        Attach
                                                    </LemonButton>
                                                </div>
                                            )}
                                        </div>

                                        <div className="flex mr-1 items-start gap-1 h-full mt-1">{topActions}</div>
                                    </div>
                                ) : (
                                    <ContextDisplay size={contextDisplaySize} />
                                )}
                                {promptLength !== null && (
                                    <div
                                        className={cn(
                                            'text-xs text-right pr-1 pt-1',
                                            isOverLengthLimit ? 'text-error' : 'text-secondary'
                                        )}
                                    >
                                        {promptLength.toLocaleString()} / {maxMessageLength.toLocaleString()}
                                    </div>
                                )}
                            </div>
                        )}
                    </label>
                    <div
                        className={cn(
                            'absolute flex items-center',
                            isSharedThread && 'hidden',
                            isThreadVisible ? 'bottom-[9px] right-[9px]' : 'bottom-[7px] right-[7px]'
                        )}
                    >
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
                            <LemonButton
                                data-attr={showStopButton ? 'max-stop-generation' : 'max-send-message'}
                                type={(isThreadVisible && !hasQuestion) || showStopButton ? 'secondary' : 'primary'}
                                onClick={handleSendClick}
                                tooltip={
                                    // If there's a disabled reason tooltip shown below, don't show a tooltip here
                                    // Else, show the tooltip based on the button state
                                    disabledReason ? undefined : showStopButton ? (
                                        <>
                                            Let's bail <KeyboardShortcut enter />
                                        </>
                                    ) : isQueueingSubmission ? (
                                        <>
                                            Queue message <KeyboardShortcut enter />
                                        </>
                                    ) : (
                                        <>
                                            Let's go! <KeyboardShortcut enter />
                                        </>
                                    )
                                }
                                loading={threadLoading && !dataProcessingAccepted}
                                disabledReason={disabledReason}
                                className={disabledReason ? 'opacity-[0.5]' : ''}
                                size="small"
                                icon={showStopButton ? <IconStopFilled /> : slashCommandIcon || <IconArrowRight />}
                            />
                        </AIConsentPopoverWrapper>
                    </div>
                </div>
                {/* Info banner for conversations created during impersonation (marked as internal) */}
                {isImpersonatedInternalConversation && (
                    <div className="flex justify-start items-center gap-1 w-full px-2 py-1 bg-bg-light text-muted text-xs rounded-b-lg">
                        {SUPPORT_SESSION_NOTICE}
                    </div>
                )}
                {/* Override checkbox - shown when impersonating and viewing existing customer conversation (not internal) */}
                {!conversation?.is_internal && (isImpersonatingExistingConversation || supportOverrideEnabled) && (
                    <div className="flex justify-start gap-1 w-full p-1 bg-warning-highlight rounded-b-lg">
                        <LemonSwitch
                            checked={supportOverrideEnabled}
                            label={SUPPORT_OVERRIDE_LABEL}
                            onChange={(checked: boolean) => setSupportOverrideEnabled(checked)}
                            size="xxsmall"
                            tooltip="Support agents should create new conversations instead of using existing ones. Check this to override."
                        />
                    </div>
                )}
            </div>
        </div>
    )
})
