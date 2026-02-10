import './QuestionInput.scss'

import { offset } from '@floating-ui/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import { IconArrowRight, IconCheck, IconPencil, IconStopFilled, IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { userLogic } from 'scenes/userLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { ConversationQueueMessage } from '~/types'

import { ContextDisplay } from '../Context'
import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { MAX_SLASH_COMMANDS } from '../slash-commands'
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
            <p className="flex-1 text-sm text-secondary truncate">{message.content}</p>
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
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)
    const { question } = useValues(maxLogic)
    const { setQuestion } = useActions(maxLogic)
    const { user } = useValues(userLogic)
    const {
        conversation,
        threadLoading,
        inputDisabled,
        submissionDisabledReason,
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
    } = useValues(maxThreadLogic)
    const { askMax, stopGeneration, completeThreadGeneration, setSupportOverrideEnabled, updateQueuedMessage } =
        useActions(maxThreadLogic)
    // Show info banner for conversations created during impersonation (marked as internal)
    const isImpersonatedInternalConversation = user?.is_impersonated && conversation?.is_internal
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

    const [showAutocomplete, setShowAutocomplete] = useState(false)
    const [editingQueueId, setEditingQueueId] = useState<string | null>(null)
    const displayQueuedMessages = useMemo(() => [...queuedMessages].reverse(), [queuedMessages])
    const hasQuestion = question.trim().length > 0
    const isQueueingSubmission = queueingEnabled && threadLoading && hasQuestion
    const showStopButton = threadLoading && !isQueueingSubmission

    // Update autocomplete visibility when question changes
    useEffect(() => {
        const isSlashCommand = question[0] === '/'
        if (isSlashCommand && !showAutocomplete) {
            posthog.capture('Max slash command autocomplete shown')
        }
        setShowAutocomplete(isSlashCommand)
    }, [question, showAutocomplete])

    let disabledReason = submissionDisabledReason
    if (threadLoading && !isQueueingSubmission) {
        disabledReason = undefined
    }
    if (cancelLoading) {
        disabledReason = 'Cancelling...'
    }
    // For non-admins, disable button when consent not given (admins see popup instead)
    const isAdmin = !dataProcessingApprovalDisabledReason
    if (!dataProcessingAccepted && !isAdmin && !disabledReason) {
        disabledReason = dataProcessingApprovalDisabledReason
    }

    useEffect(() => {
        if (!streamingActive && textAreaRef?.current) {
            textAreaRef.current.focus()
        }
    }, [streamingActive]) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <div
            className={clsx(
                containerClassName,
                !isSticky && !isThreadVisible
                    ? 'px-3 w-[min(40rem,100%)]'
                    : 'sticky bottom-0 z-10 w-full max-w-180 self-center'
            )}
            ref={ref}
        >
            <div
                className={clsx(
                    'flex flex-col items-center',
                    isSticky && 'mb-2 border border-primary rounded-lg backdrop-blur-sm bg-glass-bg-3000'
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
                    {queueingEnabled && queuedMessages.length > 0 && (
                        <div className="px-3 py-2">
                            <div className="text-xs text-muted mb-1.5">Up next</div>
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
                        className={clsx(
                            'input-like flex flex-col cursor-text',
                            'border border-primary',
                            'bg-[var(--color-bg-fill-input)]',
                            isThreadVisible ? 'border-primary m-0.5 rounded-[7px]' : 'rounded-lg',
                            // for flag, we change the ring size and color
                            isRemovingSidePanelFlag && '[--input-ring-size:2px]',
                            // when streaming, we make the ring default color, and when done streaming pop back to very this purple to let users know it's their turn to type
                            // When we allow appending messages, this ux will likely not be useful
                            isRemovingSidePanelFlag && !streamingActive && '[--input-ring-color:#b62ad9]'
                        )}
                    >
                        <SlashCommandAutocomplete visible={showAutocomplete} onClose={() => setShowAutocomplete(false)}>
                            <div className="relative w-full">
                                {!question && (
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
                                                        / for commands
                                                    </span>
                                                </>
                                            )
                                        ) : (
                                            <>
                                                Ask a question{' '}
                                                <span className="text-tertiary opacity-80 contrast-more:opacity-100">
                                                    / for commands
                                                </span>
                                            </>
                                        )}
                                    </div>
                                )}
                                <LemonTextArea
                                    aria-describedby={!question ? 'textarea-hint' : undefined}
                                    id="question-input"
                                    ref={textAreaRef}
                                    value={isSharedThread ? '' : question}
                                    onChange={(value) => setQuestion(value)}
                                    onPressEnter={() => {
                                        if (
                                            hasQuestion &&
                                            !submissionDisabledReason &&
                                            (!threadLoading || queueingEnabled)
                                        ) {
                                            onSubmit?.()
                                            askMax(question)
                                        }
                                    }}
                                    onKeyDown={(event) => {
                                        if (
                                            event.key === 'ArrowUp' &&
                                            !question.trim() &&
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
                                    className="!border-none !bg-transparent min-h-16 py-2 pl-2 pr-12 resize-none"
                                    hideFocus
                                />
                            </div>
                        </SlashCommandAutocomplete>

                        {!isSharedThread && (
                            <div className="pb-2">
                                {!isThreadVisible ? (
                                    <div className="flex items-start justify-between">
                                        <ContextDisplay size={contextDisplaySize} />
                                        <div className="flex items-start gap-1 h-full mt-1 mr-1">{topActions}</div>
                                    </div>
                                ) : (
                                    <ContextDisplay size={contextDisplaySize} />
                                )}
                            </div>
                        )}
                    </label>
                    <div
                        className={clsx(
                            'absolute flex items-center',
                            isSharedThread && 'hidden',
                            isThreadVisible ? 'bottom-[9px] right-[9px]' : 'bottom-[7px] right-[7px]'
                        )}
                    >
                        <AIConsentPopoverWrapper
                            placement="bottom-end"
                            showArrow
                            onApprove={() => askMax(pendingPrompt || question)}
                            onDismiss={() => completeThreadGeneration()}
                            middleware={[
                                offset((state) => ({
                                    mainAxis: state.placement.includes('top') ? 30 : 1,
                                })),
                            ]}
                            hidden={!isAdmin || (!threadLoading && !pendingPrompt)}
                        >
                            <LemonButton
                                type={(isThreadVisible && !hasQuestion) || showStopButton ? 'secondary' : 'primary'}
                                onClick={() => {
                                    if (threadLoading) {
                                        if (isQueueingSubmission) {
                                            if (submissionDisabledReason) {
                                                textAreaRef?.current?.focus()
                                                return
                                            }
                                            askMax(question)
                                            return
                                        }
                                        stopGeneration()
                                        return
                                    }
                                    if (submissionDisabledReason) {
                                        textAreaRef?.current?.focus()
                                        return
                                    }
                                    askMax(question)
                                }}
                                tooltip={
                                    disabledReason ? (
                                        disabledReason
                                    ) : showStopButton ? (
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
                                        MAX_SLASH_COMMANDS.find((cmd) => cmd.name === question.split(' ', 1)[0])
                                            ?.icon || <IconArrowRight />
                                    )
                                }
                            />
                        </AIConsentPopoverWrapper>
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
            <p className="w-full flex text-xs text-muted mt-1">
                <span className="mx-auto">PostHog AI can make mistakes. Please double-check responses.</span>
            </p>
        </div>
    )
})
