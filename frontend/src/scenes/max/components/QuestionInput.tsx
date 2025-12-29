import './QuestionInput.scss'

import { offset } from '@floating-ui/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import React, { ReactNode, useEffect, useState } from 'react'

import { IconArrowRight, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { userLogic } from 'scenes/userLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

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
    } = useValues(maxThreadLogic)
    const { askMax, stopGeneration, completeThreadGeneration, setSupportOverrideEnabled } = useActions(maxThreadLogic)

    // Show info banner for conversations created during impersonation (marked as internal)
    const isImpersonatedInternalConversation = user?.is_impersonated && conversation?.is_internal

    const [showAutocomplete, setShowAutocomplete] = useState(false)

    // Update autocomplete visibility when question changes
    useEffect(() => {
        const isSlashCommand = question[0] === '/'
        if (isSlashCommand && !showAutocomplete) {
            posthog.capture('Max slash command autocomplete shown')
        }
        setShowAutocomplete(isSlashCommand)
    }, [question, showAutocomplete])

    let disabledReason = !threadLoading
        ? !dataProcessingAccepted
            ? 'Pending approval'
            : submissionDisabledReason
        : undefined
    if (cancelLoading) {
        disabledReason = 'Cancelling...'
    }

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
                    <label
                        htmlFor="question-input"
                        className={clsx(
                            'input-like flex flex-col cursor-text',
                            'border border-primary',
                            'bg-[var(--color-bg-fill-input)]',
                            isThreadVisible ? 'border-primary m-0.5 rounded-[7px]' : 'rounded-lg'
                        )}
                    >
                        <SlashCommandAutocomplete visible={showAutocomplete} onClose={() => setShowAutocomplete(false)}>
                            <div className="relative w-full">
                                {!question && (
                                    <div id="textarea-hint" className="text-secondary absolute top-4 left-4 text-sm">
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
                                        if (question && !submissionDisabledReason && !threadLoading) {
                                            onSubmit?.()
                                            askMax(question)
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
                            hidden={!threadLoading}
                        >
                            <LemonButton
                                type={(isThreadVisible && !question) || threadLoading ? 'secondary' : 'primary'}
                                onClick={() => {
                                    if (threadLoading) {
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
                                    ) : threadLoading ? (
                                        <>
                                            Let's bail <KeyboardShortcut enter />
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
                                    threadLoading ? (
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
        </div>
    )
})
