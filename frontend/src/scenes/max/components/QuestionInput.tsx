import './QuestionInput.scss'

import { offset } from '@floating-ui/react'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconArrowRight, IconCheck, IconPencil, IconStopFilled, IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonSwitch, Spinner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { userLogic } from 'scenes/userLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { ConversationQueueMessage } from '~/types'

import { AutosizeTextArea } from 'products/posthog_ai/frontend/api/primitives'

import { ContextDisplay } from '../Context'
import { handsFreeLogic } from '../handsFreeLogic'
import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { MAX_SLASH_COMMANDS } from '../slash-commands'
import { FillInHint } from './FillInHint'
import { HandsFreeButton } from './HandsFreeButton'
import { HandsFreeSurface } from './HandsFreeSurface'
import { SlashCommandAutocomplete } from './SlashCommandAutocomplete'

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

function QueuedMessageItem({
    message,
    isEditing,
    onEdit,
    onCancel,
    onSave,
}: {
    message: ConversationQueueMessage
    isEditing: boolean
    onEdit: () => void
    onCancel: () => void
    onSave: (messageId: string, content: string) => void
}): JSX.Element {
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
                <AutosizeTextArea
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
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const { question, panelId: maxPanelId, fillInHint } = useValues(maxLogic)
    const { setQuestion, setFillInHint } = useActions(maxLogic)
    const { user } = useValues(userLogic)
    const {
        conversation,
        threadLoading,
        inputDisabled,
        contextDisabledReason,
        queueDisabledReason,
        isSharedThread,
        cancelLoading,
        pendingPrompt,
        isImpersonatingExistingConversation,
        supportOverrideEnabled,
        streamingActive,
        agentMode,
        threadMessageCount,
        queueingEnabled,
        queuedMessages,
        queueSubmitting,
    } = useValues(maxThreadLogic)
    const {
        askMax,
        stopGeneration,
        completeThreadGeneration,
        setSupportOverrideEnabled,
        updateQueuedMessage,
        releaseSandboxPrewarm,
    } = useActions(maxThreadLogic)
    const { isActive: handsFreeActive } = useValues(handsFreeLogic({ panelId: maxPanelId }))
    // Only the hands-free row needs bottom-aligned pills — it has the mic + submit pair
    // pinned to the bottom and pills sitting in normal flow look misaligned next to them.
    // Keep the legacy items-start layout when the flag is off so existing screenshots
    // (and the layout users without hands-free see) don't change.
    const handsFreeFlagEnabled = useFeatureFlag('MAX_HANDS_FREE')
    // Show info banner for conversations created during impersonation (marked as internal)
    const isImpersonatedInternalConversation = user?.is_impersonated && conversation?.is_internal

    const [showAutocomplete, setShowAutocomplete] = useState(false)
    // Tracks an explicit dismissal (e.g. Esc) so the popover stays closed while the
    // user keeps typing a message that still starts with "/". "/" + Esc is a valid path.
    const [autocompleteDismissed, setAutocompleteDismissed] = useState(false)
    const [editingQueueId, setEditingQueueId] = useState<string | null>(null)
    const displayQueuedMessages = useMemo(() => [...queuedMessages].reverse(), [queuedMessages])

    // Hold the textarea value in local state so each keystroke is an isolated, cheap re-render
    // rather than a global kea dispatch. Binding the input directly to kea made every keystroke
    // notify every store subscriber, so input lag grew with conversation length (more mounted
    // messages = more subscriptions to sweep). kea remains the source of truth for submit, slash
    // commands, and draft persistence — we sync to it on a debounce, immediately for slash
    // commands so the autocomplete stays responsive, and on submit/blur.
    const [inputValue, setInputValue] = useState(question)
    const debouncedSetQuestion = useDebouncedCallback((value: string) => setQuestion(value), 150)

    // Flush any pending debounce when the component unmounts so that a draft typed just
    // before programmatic navigation (no blur event) is still persisted to kea.
    useEffect(() => {
        return () => debouncedSetQuestion.flush()
    }, [debouncedSetQuestion])

    // Mirror external question changes (draft restore, slash command insertion, clear on submit)
    // back into local state. Writing the same value is a no-op, so the debounced sync below
    // doesn't cause an extra render.
    useEffect(() => {
        setInputValue(question)
    }, [question])

    const handleQuestionChange = (value: string): void => {
        setInputValue(value)
        // The user typing their own text ends the fill-in cue.
        if (fillInHint) {
            setFillInHint(null)
        }
        if (value.startsWith('/')) {
            // Slash commands drive the autocomplete off kea's `question`, so sync immediately.
            debouncedSetQuestion.cancel()
            setQuestion(value)
        } else {
            debouncedSetQuestion(value)
        }
    }

    const submit = (prompt: string): void => {
        // askMax reads the prompt arg directly and clears `question` afterwards, so drop any
        // pending debounce to stop it from re-populating the just-sent text.
        debouncedSetQuestion.cancel()
        if (fillInHint) {
            setFillInHint(null)
        }
        askMax(prompt)
    }

    const hasQuestion = inputValue.trim().length > 0
    // A fill-in suggestion typed its prefix in and is waiting for the user to complete it.
    const showFillInHint = !!fillInHint
    const isQueueingSubmission = queueingEnabled && threadLoading && hasQuestion
    const showStopButton = threadLoading && !isQueueingSubmission && !cancelLoading

    // Mirrors maxThreadLogic's `submissionDisabledReason` selector, but using the local input
    // value so the submit guard stays correct while the debounced sync to kea is still pending.
    const submissionDisabledReason = contextDisabledReason
        ? contextDisabledReason
        : !inputValue
          ? 'I need some input first'
          : queueDisabledReason

    // Update autocomplete visibility when the input changes
    useEffect(() => {
        const isSlashCommand = inputValue[0] === '/'
        // Once the input is no longer a slash command, clear any prior dismissal so
        // typing "/" again later reopens the popover.
        if (!isSlashCommand && autocompleteDismissed) {
            setAutocompleteDismissed(false)
        }
        const shouldShow = isSlashCommand && !autocompleteDismissed
        if (shouldShow && !showAutocomplete) {
            posthog.capture('Max slash command autocomplete shown')
        }
        setShowAutocomplete(shouldShow)
    }, [inputValue, showAutocomplete, autocompleteDismissed])

    let disabledReason = submissionDisabledReason
    if (threadLoading && !isQueueingSubmission) {
        disabledReason = undefined
    }
    if (cancelLoading) {
        disabledReason = 'Cancelling...'
    }

    useEffect(() => {
        if (!streamingActive && textAreaRef?.current) {
            textAreaRef.current.focus()
        }
    }, [streamingActive]) // oxlint-disable-line react-hooks/exhaustive-deps

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
                    {agentMode === AgentMode.Research && threadMessageCount === 0 && (
                        <div className="flex justify-center items-center gap-1 w-full px-2 py-1.5 mb-2 bg-warning/10 text-primary text-xs rounded-lg border-primary">
                            Research mode is a free beta feature with lower daily limits
                        </div>
                    )}
                    {queueingEnabled && (queuedMessages.length > 0 || queueSubmitting) && (
                        <div className="px-3 py-2">
                            <div className="text-xs text-muted mb-1.5 flex items-center gap-1.5">
                                Up next
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
                                        onSave={(messageId, content) => {
                                            updateQueuedMessage(messageId, content)
                                            setEditingQueueId(null)
                                        }}
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
                        {handsFreeActive ? (
                            <HandsFreeSurface panelId={maxPanelId} />
                        ) : (
                            <SlashCommandAutocomplete
                                visible={showAutocomplete}
                                onClose={() => {
                                    setShowAutocomplete(false)
                                    setAutocompleteDismissed(true)
                                }}
                            >
                                <div className="relative w-full">
                                    {!inputValue && (
                                        <div
                                            id="textarea-hint"
                                            className="text-secondary absolute top-4 left-4 text-sm pointer-events-none"
                                        >
                                            {conversation && isSharedThread ? (
                                                `This thread was shared with you by ${conversation.user.first_name} ${conversation.user.last_name}`
                                            ) : threadLoading ? (
                                                'Thinking…'
                                            ) : isThreadVisible ? (
                                                placeholder || (
                                                    <>
                                                        Ask follow-up{' '}
                                                        <span className="text-tertiary opacity-80 contrast-more:opacity-100">
                                                            or / for commands
                                                        </span>
                                                    </>
                                                )
                                            ) : (
                                                <>
                                                    Ask a question{' '}
                                                    <span className="text-tertiary opacity-80 contrast-more:opacity-100">
                                                        or / for commands
                                                    </span>
                                                </>
                                            )}
                                        </div>
                                    )}
                                    {/* Postfix cue after a fill-in suggestion's typed-in prefix. */}
                                    {showFillInHint && (
                                        <div className="absolute top-4 left-4 right-4 overflow-hidden pointer-events-none">
                                            <FillInHint text={inputValue} hint={fillInHint} />
                                        </div>
                                    )}
                                    <AutosizeTextArea
                                        aria-describedby={!inputValue ? 'textarea-hint' : undefined}
                                        id="question-input"
                                        data-attr="max-chat-input"
                                        ref={textAreaRef}
                                        value={isSharedThread ? '' : inputValue}
                                        onChange={handleQuestionChange}
                                        onBlur={(e) => {
                                            debouncedSetQuestion.flush()
                                            // Release any sandbox pre-warm when the user leaves the
                                            // input without sending. No-op on LangGraph / unwarmed
                                            // conversations.
                                            //
                                            // But clicking the send button blurs the textarea *before*
                                            // its onClick fires the send — releasing here would cancel
                                            // the very warm Run the send is about to consume. When focus
                                            // moves to the send button, skip the release and let the send
                                            // path consume the warm (it does so without a DELETE).
                                            const next = e.relatedTarget as HTMLElement | null
                                            if (next?.closest('[data-attr="max-send-message"]')) {
                                                return
                                            }
                                            releaseSandboxPrewarm()
                                        }}
                                        onPressEnter={() => {
                                            if (
                                                hasQuestion &&
                                                !submissionDisabledReason &&
                                                (!threadLoading || queueingEnabled)
                                            ) {
                                                onSubmit?.()
                                                submit(inputValue)
                                            }
                                        }}
                                        onKeyDown={(event) => {
                                            if (
                                                event.key === 'ArrowUp' &&
                                                !inputValue.trim() &&
                                                queuedMessages.length > 0 &&
                                                !editingQueueId
                                            ) {
                                                const target = event.currentTarget
                                                const atStart = target.selectionStart === 0 && target.selectionEnd === 0
                                                const isSingleLine = target.value.split('\n').length <= 1
                                                if (!atStart || !isSingleLine) {
                                                    return
                                                }
                                                const nextMessageId = queuedMessages[0]?.id
                                                if (!nextMessageId) {
                                                    return
                                                }
                                                event.preventDefault()
                                                setEditingQueueId(nextMessageId)
                                            }
                                        }}
                                        disabled={inputDisabled}
                                        minRows={1}
                                        maxRows={10}
                                        className="py-2 pl-2"
                                        textareaClassName={cn(
                                            '!border-none !bg-transparent min-h-16 resize-none',
                                            handsFreeFlagEnabled ? 'pr-20' : 'pr-12',
                                            // Hide the native caret so only the enlarged fill-in caret shows.
                                            showFillInHint && 'caret-transparent'
                                        )}
                                        hideFocus
                                    />
                                </div>
                            </SlashCommandAutocomplete>
                        )}

                        {!isSharedThread && !handsFreeActive && (
                            // When the hands-free flag is on, reserve ~80px (pr-20) so the chip
                            // row doesn't wrap under the absolutely-positioned mic + send pair.
                            // Without the flag the row only has send and the legacy pr-12 is
                            // enough — keep it so non-flagged users see the original layout.
                            <div className={cn('pb-2', handsFreeFlagEnabled ? 'pr-20' : 'pr-12')}>
                                {!isThreadVisible ? (
                                    <div
                                        className={cn(
                                            'flex justify-between',
                                            handsFreeFlagEnabled ? 'items-end flex-wrap gap-1' : 'items-start'
                                        )}
                                    >
                                        <ContextDisplay size={contextDisplaySize} />

                                        <div
                                            className={cn(
                                                'flex mr-1',
                                                handsFreeFlagEnabled
                                                    ? 'items-end gap-1'
                                                    : 'items-start gap-1 h-full mt-1'
                                            )}
                                        >
                                            {topActions}
                                        </div>
                                    </div>
                                ) : (
                                    <ContextDisplay size={contextDisplaySize} />
                                )}
                            </div>
                        )}
                    </label>
                    <div
                        className={cn(
                            'absolute flex items-center',
                            handsFreeFlagEnabled && 'gap-1',
                            isSharedThread && 'hidden',
                            isThreadVisible ? 'bottom-[9px] right-[9px]' : 'bottom-[7px] right-[7px]'
                        )}
                    >
                        <HandsFreeButton panelId={maxPanelId} />
                        {!handsFreeActive && (
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
                                    onClick={() => {
                                        if (threadLoading) {
                                            if (isQueueingSubmission) {
                                                if (submissionDisabledReason) {
                                                    textAreaRef?.current?.focus()
                                                    return
                                                }
                                                submit(inputValue)
                                                return
                                            }
                                            stopGeneration()
                                            return
                                        }
                                        if (submissionDisabledReason) {
                                            textAreaRef?.current?.focus()
                                            return
                                        }
                                        submit(inputValue)
                                    }}
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
                                    icon={
                                        showStopButton ? (
                                            <IconStopFilled />
                                        ) : (
                                            MAX_SLASH_COMMANDS.find((cmd) => cmd.name === inputValue.split(' ', 1)[0])
                                                ?.icon || <IconArrowRight />
                                        )
                                    }
                                />
                            </AIConsentPopoverWrapper>
                        )}
                    </div>
                </div>
                {/* Info banner for conversations created during impersonation (marked as internal) */}
                {isImpersonatedInternalConversation && (
                    <div className="flex justify-start items-center gap-1 w-full px-2 py-1 bg-bg-light text-muted text-xs rounded-b-lg">
                        Support agent session — this conversation won't be visible to the customer
                    </div>
                )}
                {/* Override checkbox - shown when impersonating and viewing existing customer conversation (not internal) */}
                {!conversation?.is_internal && (isImpersonatingExistingConversation || supportOverrideEnabled) && (
                    <div className="flex justify-start gap-1 w-full p-1 bg-warning-highlight rounded-b-lg">
                        <LemonSwitch
                            checked={supportOverrideEnabled}
                            label="I understand this will add to the customer's conversation"
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
