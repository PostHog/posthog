import { offset } from '@floating-ui/react'
import { IconArrowRight, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonTextArea, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ReactNode, useState, useEffect, useMemo, useRef } from 'react'
import React from 'react'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { useResizeObserver } from '~/lib/hooks/useResizeObserver'

import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { ContextDisplay } from '../Context'
import { SlashCommandAutocomplete } from './SlashCommandAutocomplete'
import posthog from 'posthog-js'
import { MAX_SLASH_COMMANDS } from '../slash-commands'
import { ToolDefinition } from '../maxGlobalLogic'

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

const ToolsDisplay: React.FC<ToolsDisplayProps> = ({ isFloating, tools, bottomActions }) => {
    const containerRef = useRef<HTMLDivElement>(null)
    const [visibleCount, setVisibleCount] = useState(tools.length)

    const { ref } = useResizeObserver<HTMLDivElement>({
        ref: containerRef,
        onResize: ({ width = 0 }) => {
            if (width > 0 && containerRef.current) {
                // Measure how many tools can fit in the available width
                const tempContainer = document.createElement('div')
                tempContainer.style.position = 'absolute'
                tempContainer.style.visibility = 'hidden'
                tempContainer.style.display = 'flex'
                tempContainer.style.flexWrap = 'wrap'
                tempContainer.style.gap = '4px'
                tempContainer.style.fontSize = '12px'
                tempContainer.style.fontWeight = '500'
                tempContainer.style.paddingLeft = '6px'
                tempContainer.style.paddingRight = '6px'
                tempContainer.style.whiteSpace = 'nowrap'

                document.body.appendChild(tempContainer)

                // Add "Tools available:" text
                const prefixSpan = document.createElement('span')
                prefixSpan.textContent = 'Tools available: '
                tempContainer.appendChild(prefixSpan)

                let count = 0
                const maxWidth = width - 12 // Account for padding

                // Try adding tools one by one
                for (let i = 0; i < tools.length; i++) {
                    const toolSpan = document.createElement('span')
                    toolSpan.style.display = 'inline-flex'
                    toolSpan.style.alignItems = 'center'
                    toolSpan.style.gap = '2px'
                    toolSpan.style.padding = '1px 4px'
                    toolSpan.style.borderRadius = '4px'
                    toolSpan.style.backgroundColor = 'var(--color-border-light)'
                    toolSpan.textContent = tools[i].displayName

                    tempContainer.appendChild(toolSpan)

                    // Check if we need to show "+ n more" instead
                    const remainingTools = tools.length - i
                    if (remainingTools > 1) {
                        const moreSpan = document.createElement('span')
                        moreSpan.textContent = `+ ${remainingTools} more`
                        moreSpan.style.padding = '1px 4px'
                        moreSpan.style.borderRadius = '4px'
                        moreSpan.style.backgroundColor = 'var(--color-border-light)'
                        tempContainer.appendChild(moreSpan)

                        if (tempContainer.scrollWidth > maxWidth) {
                            // Remove the "+ n more" and the current tool
                            tempContainer.removeChild(moreSpan)
                            tempContainer.removeChild(toolSpan)
                            break
                        } else {
                            // Remove the "+ n more" for now, we'll add it back if needed
                            tempContainer.removeChild(moreSpan)
                        }
                    }

                    if (tempContainer.scrollWidth > maxWidth) {
                        // This tool doesn't fit, remove it
                        tempContainer.removeChild(toolSpan)
                        break
                    }

                    count = i + 1
                }

                document.body.removeChild(tempContainer)
                setVisibleCount(count)
            }
        },
    })

    const visibleTools = useMemo(() => tools.slice(0, visibleCount), [tools, visibleCount])
    const hiddenCount = tools.length - visibleCount

    return (
        <div className="flex items-center w-full gap-1 justify-center">
            <Tooltip
                placement="bottom"
                title={
                    <div className="max-w-[28rem] text-left">
                        <div className="mb-2">
                            <div className="font-semibold mb-1">What Max can do</div>
                            <ul className="space-y-0.5 text-sm">
                                <li className="flex items-center gap-2">
                                    <span className="inline-block size-2 rounded-full bg-success shrink-0" />
                                    <span>Create and query insights</span>
                                </li>
                                <li className="flex items-center gap-2">
                                    <span className="inline-block size-2 rounded-full bg-success shrink-0" />
                                    <span>Generate and fix HogQL queries</span>
                                </li>
                                <li className="flex items-center gap-2">
                                    <span className="inline-block size-2 rounded-full bg-success shrink-0" />
                                    <span>Search session recordings</span>
                                </li>
                                <li className="flex items-center gap-2">
                                    <span className="inline-block size-2 rounded-full bg-success shrink-0" />
                                    <span>Analyze user interviews</span>
                                </li>
                                <li className="flex items-center gap-2">
                                    <span className="inline-block size-2 rounded-full bg-success shrink-0" />
                                    <span>Create surveys</span>
                                </li>
                                <li className="flex items-center gap-2">
                                    <span className="inline-block size-2 rounded-full bg-success shrink-0" />
                                    <span>Navigate to relevant places in PostHog</span>
                                </li>
                                <li className="flex items-center gap-2">
                                    <span className="inline-block size-2 rounded-full bg-success shrink-0" />
                                    <span>Search error tracking issues</span>
                                </li>
                                <li className="flex items-center gap-2">
                                    <span className="inline-block size-2 rounded-full bg-success shrink-0" />
                                    <span>Summarize experiment results</span>
                                </li>
                                <li className="flex items-center gap-2">
                                    <span className="inline-block size-2 rounded-full bg-success shrink-0" />
                                    <span>Author Hog functions (transformations, filters, inputs)</span>
                                </li>
                                <li className="flex items-center gap-2">
                                    <span className="inline-block size-2 rounded-full bg-success shrink-0" />
                                    <span>Answer questions from PostHog docs</span>
                                </li>
                            </ul>
                        </div>
                        <div>
                            <div className="font-semibold mb-1">What Max can't do</div>
                            <ul className="space-y-0.5 text-sm">
                                <li className="flex items-center gap-2">
                                    <span className="inline-block size-2 rounded-full bg-danger shrink-0" />
                                    <span>Access your infrastructure, source code, or third‑party tools</span>
                                </li>
                                <li className="flex items-center gap-2">
                                    <span className="inline-block size-2 rounded-full bg-danger shrink-0" />
                                    <span>Browse the web beyond PostHog documentation</span>
                                </li>
                                <li className="flex items-center gap-2">
                                    <span className="inline-block size-2 rounded-full bg-danger shrink-0" />
                                    <span>See data outside this PostHog project</span>
                                </li>
                                <li className="flex items-center gap-2">
                                    <span className="inline-block size-2 rounded-full bg-danger shrink-0" />
                                    <span>Guarantee correctness of the queries created</span>
                                </li>
                            </ul>
                        </div>
                    </div>
                }
            >
                <div
                    ref={ref}
                    className={clsx(
                        'flex flex-wrap items-center gap-1 text-xs font-medium cursor-default px-1.5 whitespace-nowrap cursor-help',
                        !isFloating
                            ? 'w-[calc(100%-1rem)] py-1 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)]'
                            : `w-full pb-1`
                    )}
                >
                    <span>Tools available:</span>
                    {visibleTools.map((tool) => (
                        <em key={tool.name} className="inline-flex items-center gap-1">
                            {tool.icon && <span className="flex items-center text-sm">{tool.icon}</span>}
                            {tool.displayName}
                        </em>
                    ))}
                    {hiddenCount > 0 && (
                        <span className="px-1.5 py-0.5 rounded text-xs bg-border-light">+ {hiddenCount} more</span>
                    )}
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
                <ToolsDisplay isFloating={isFloating} tools={tools} bottomActions={bottomActions} />
            </div>
        </div>
    )
})
