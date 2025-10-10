import './QuestionInput.scss'

import { offset } from '@floating-ui/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { ReactNode, useEffect, useState } from 'react'
import React from 'react'

import { IconArrowRight, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { ContextDisplay } from '../Context'
import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { MAX_SLASH_COMMANDS } from '../slash-commands'
import { SlashCommandAutocomplete } from './SlashCommandAutocomplete'
import { ToolsDisplay } from './ToolsDisplay'

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
    showDeepResearchModeToggle?: boolean
}

export const QuestionInput = React.forwardRef<HTMLDivElement, QuestionInputProps>(function BaseQuestionInput(
    {
        isSticky,
        placeholder,
        children,
        contextDisplaySize,
        isThreadVisible,
        topActions,
        bottomActions,
        textAreaRef,
        containerClassName,
        onSubmit,
        showDeepResearchModeToggle,
    },
    ref
) {
    const { dataProcessingAccepted, tools } = useValues(maxGlobalLogic)
    const { question } = useValues(maxLogic)
    const { setQuestion } = useActions(maxLogic)
    const { threadLoading, inputDisabled, submissionDisabledReason, deepResearchMode } = useValues(maxThreadLogic)
    const { askMax, stopGeneration, completeThreadGeneration, setDeepResearchMode } = useActions(maxThreadLogic)

    const [showAutocomplete, setShowAutocomplete] = useState(false)

    // Update autocomplete visibility when question changes
    useEffect(() => {
        const isSlashCommand = question[0] === '/'
        if (isSlashCommand && !showAutocomplete) {
            posthog.capture('Max slash command autocomplete shown')
        }
        setShowAutocomplete(isSlashCommand)
    }, [question, showAutocomplete])

    return (
        <div
            className={clsx(
                containerClassName,
                !isSticky && !isThreadVisible
                    ? 'px-3 w-[min(40rem,100%)]'
                    : 'sticky bottom-0 z-10 w-full max-w-[45.25rem] self-center'
            )}
            ref={ref}
        >
            <div
                className={clsx(
                    'flex flex-col items-center',
                    isSticky &&
                        'mb-2 border border-[var(--color-border-primary)] rounded-lg backdrop-blur-sm bg-[var(--glass-bg-3000)]'
                )}
            >
                {/* Have to increase z-index to overlay ToolsDisplay */}
                <div className="relative w-full flex flex-col z-1">
                    {children}
                    <div
                        className={clsx(
                            'flex flex-col',
                            'border border-[var(--color-border-primary)]',
                            'bg-[var(--color-bg-fill-input)]',
                            'hover:border-border-bold focus-within:border-border-bold',
                            isThreadVisible ? 'border-primary m-0.5 rounded-[10px]' : 'rounded-lg'
                        )}
                        onClick={(e) => {
                            // If user clicks anywhere with the area with a hover border, activate input - except on button clicks
                            if (!(e.target as HTMLElement).closest('button')) {
                                textAreaRef?.current?.focus()
                            }
                        }}
                    >
                        <div className="pt-1">
                            {!isThreadVisible ? (
                                <div className="flex items-start justify-between">
                                    <ContextDisplay size={contextDisplaySize} />
                                    <div className="flex items-start gap-1 h-full mt-1 mr-1">{topActions}</div>
                                </div>
                            ) : (
                                <ContextDisplay size={contextDisplaySize} />
                            )}
                        </div>

                        <SlashCommandAutocomplete visible={showAutocomplete} onClose={() => setShowAutocomplete(false)}>
                            <LemonTextArea
                                ref={textAreaRef}
                                value={question}
                                onChange={setQuestion}
                                placeholder={
                                    threadLoading
                                        ? 'Thinking…'
                                        : isThreadVisible
                                          ? placeholder || 'Ask follow-up (/ for commands)'
                                          : 'Ask away (/ for commands)'
                                }
                                onPressEnter={() => {
                                    if (question && !submissionDisabledReason && !threadLoading) {
                                        onSubmit?.()
                                        askMax(question)
                                    }
                                }}
                                disabled={inputDisabled}
                                minRows={1}
                                maxRows={10}
                                className="!border-none !bg-transparent min-h-0 py-2.5 pl-2.5 pr-12"
                            />
                        </SlashCommandAutocomplete>
                    </div>
                    <div
                        className={clsx(
                            'absolute flex items-center',
                            isThreadVisible ? 'bottom-[9px] right-[9px]' : 'bottom-[7px] right-[7px]'
                        )}
                    >
                        <AIConsentPopoverWrapper
                            placement="bottom-end"
                            showArrow
                            onApprove={() => askMax(question)}
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
                                    } else {
                                        askMax(question)
                                    }
                                }}
                                tooltip={
                                    threadLoading ? (
                                        "Let's bail"
                                    ) : (
                                        <>
                                            Let's go! <KeyboardShortcut enter />
                                        </>
                                    )
                                }
                                loading={threadLoading && !dataProcessingAccepted}
                                disabledReason={
                                    threadLoading && !dataProcessingAccepted
                                        ? 'Pending approval'
                                        : submissionDisabledReason
                                }
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
                <ToolsDisplay
                    isFloating={isThreadVisible}
                    tools={tools}
                    bottomActions={bottomActions}
                    deepResearchMode={deepResearchMode}
                />
                {showDeepResearchModeToggle && (
                    <div className="flex justify-end gap-1 w-full p-1">
                        <LemonSwitch
                            checked={deepResearchMode}
                            label="Think harder"
                            disabled={threadLoading}
                            onChange={(checked) => setDeepResearchMode(checked)}
                            size="xxsmall"
                            tooltip="This will make Max think harder about your question"
                        />
                    </div>
                )}
            </div>
        </div>
    )
})
