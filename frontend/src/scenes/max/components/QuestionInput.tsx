import { offset } from '@floating-ui/react'
import { IconArrowRight, IconStopFilled, IconCheck, IconX } from '@posthog/icons'
import { LemonButton, LemonTextArea, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ReactNode, useState, useEffect } from 'react'
import React from 'react'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
// import { useResizeObserver } from '~/lib/hooks/useResizeObserver'

import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { ContextDisplay } from '../Context'
import { SlashCommandAutocomplete } from './SlashCommandAutocomplete'
import posthog from 'posthog-js'
import { MAX_SLASH_COMMANDS } from '../slash-commands'
import { ToolDefinition } from '../maxGlobalLogic'
import './QuestionInput.scss'

export const MAX_CAN = [
    'Query data',
    'Generate and fix HogQL queries',
    'Search session recordings',
    'Analyze user interviews',
    'Create surveys',
    'Navigate to relevant places in PostHog',
    'Search error tracking issues',
    'Summarize experiment results',
    'Author Hog functions (transformations, filters, inputs)',
    'Answer questions from PostHog docs',
] as const

export const MAX_CANNOT = [
    'Access your infrastructure, source code, or third‑party tools',
    'Browse the web beyond PostHog documentation',
    'See data outside this PostHog project',
    'Guarantee correctness of the queries created',
] as const

interface QuestionInputProps {
    isFloating?: boolean
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

interface ToolsDisplayProps {
    isFloating?: boolean
    tools: ToolDefinition[]
    bottomActions?: ReactNode
}

const ToolsMarquee: React.FC<ToolsDisplayProps> = ({ isFloating, tools, bottomActions }) => {
    return (
        <div className="flex items-center w-full gap-1 justify-center">
            <Tooltip
                placement="bottom"
                title={
                    <div className="max-w-[28rem] text-left">
                        <div className="mb-2">
                            <div className="font-semibold mb-1">What Max can do</div>
                            <ul className="space-y-0.5 text-sm">
                                {MAX_CAN.map((item) => (
                                    <li key={item} className="flex items-center">
                                        <IconCheck className="text-base text-success shrink-0 mx-2" />
                                        <span>{item}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                        <div>
                            <div className="font-semibold mb-1">What Max can't do</div>
                            <ul className="space-y-0.5 text-sm">
                                {MAX_CANNOT.map((item) => (
                                    <li key={item} className="flex items-center">
                                        <IconX className="text-base text-danger shrink-0 mx-2" />
                                        <span>{item}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    </div>
                }
            >
                <div
                    className={clsx(
                        'relative flex items-center text-xs font-medium cursor-help',
                        !isFloating
                            ? 'w-[calc(100%-1rem)] py-1 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)]'
                            : `w-full pb-1`
                    )}
                >
                    <div className="relative flex-1 overflow-hidden">
                        <div className="QuestionInput__ToolsMarquee__track">
                            <div className="QuestionInput__ToolsMarquee__content">
                                <span className="shrink-0">Tools available:</span>
                                {tools.map((tool) => (
                                    <em key={`a-${tool.name}`} className="inline-flex items-center gap-1">
                                        {tool.icon && <span className="flex items-center text-sm">{tool.icon}</span>}
                                        {tool.displayName}
                                    </em>
                                ))}
                            </div>
                            <div className="QuestionInput__ToolsMarquee__content" aria-hidden>
                                <span className="shrink-0">Tools available:</span>
                                {tools.map((tool) => (
                                    <em key={`b-${tool.name}`} className="inline-flex items-center gap-1">
                                        {tool.icon && <span className="flex items-center text-sm">{tool.icon}</span>}
                                        {tool.displayName}
                                    </em>
                                ))}
                            </div>
                        </div>
                        {/* Edge fades */}
                        <span
                            aria-hidden
                            className={clsx(
                                'pointer-events-none absolute left-0 top-0 h-full w-6',
                                'bg-gradient-to-r from-[var(--glass-bg-3000)] to-transparent'
                            )}
                        />
                        <span
                            aria-hidden
                            className={clsx(
                                'pointer-events-none absolute right-0 top-0 h-full w-6',
                                'bg-gradient-to-l from-[var(--glass-bg-3000)] to-transparent'
                            )}
                        />
                    </div>
                </div>
            </Tooltip>
            {bottomActions && <div className="ml-auto">{bottomActions}</div>}
        </div>
    )
}

export const QuestionInput = React.forwardRef<HTMLDivElement, QuestionInputProps>(function BaseQuestionInput(
    {
        isFloating,
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
    },
    ref
) {
    const { dataProcessingAccepted, tools } = useValues(maxGlobalLogic)
    const { question } = useValues(maxLogic)
    const { setQuestion } = useActions(maxLogic)
    const { threadLoading, inputDisabled, submissionDisabledReason } = useValues(maxThreadLogic)
    const { askMax, stopGeneration, completeThreadGeneration } = useActions(maxThreadLogic)

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
                !isSticky && !isFloating
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
                <div className="relative w-full flex flex-col">
                    {children}
                    <div
                        className={clsx(
                            'flex flex-col',
                            'border border-[var(--color-border-primary)] rounded-[var(--radius)]',
                            'bg-[var(--color-bg-fill-input)]',
                            'hover:border-[var(--border-bold)] focus-within:border-[var(--border-bold)]',
                            isFloating && 'border-primary m-1'
                        )}
                        onClick={(e) => {
                            // If user clicks anywhere with the area with a hover border, activate input - except on button clicks
                            if (!(e.target as HTMLElement).closest('button')) {
                                textAreaRef?.current?.focus()
                            }
                        }}
                    >
                        {!isThreadVisible ? (
                            <div className="flex items-start justify-between">
                                <ContextDisplay size={contextDisplaySize} />
                                <div className="flex items-start gap-1 h-full mt-1 mr-1">{topActions}</div>
                            </div>
                        ) : (
                            <ContextDisplay size={contextDisplaySize} />
                        )}

                        <SlashCommandAutocomplete visible={showAutocomplete} onClose={() => setShowAutocomplete(false)}>
                            <LemonTextArea
                                ref={textAreaRef}
                                value={question}
                                onChange={setQuestion}
                                placeholder={
                                    threadLoading
                                        ? 'Thinking…'
                                        : isFloating
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
                        className={clsx('absolute flex items-center', {
                            'bottom-[11px] right-3': isFloating,
                            'bottom-[7px] right-2': !isFloating,
                        })}
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
                                type={(isFloating && !question) || threadLoading ? 'secondary' : 'primary'}
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
                <ToolsMarquee isFloating={isFloating} tools={tools} bottomActions={bottomActions} />
            </div>
        </div>
    )
})
