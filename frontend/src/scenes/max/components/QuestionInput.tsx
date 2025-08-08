import { offset } from '@floating-ui/react'
import { IconArrowRight, IconStopFilled, IconCheck, IconX, IconWrench, IconInfo } from '@posthog/icons'
import { LemonButton, LemonTextArea, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ReactNode, useState, useEffect, useRef } from 'react'
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
import './QuestionInput.scss'
import { AssistantContextualTool } from '~/queries/schema/schema-assistant-messages'

export const MAX_CAN = [
    'Query your analytics data and data warehouse',
    'Answer questions from PostHog docs',
    'Navigate to relevant places in PostHog',
    'Read and analyze attached context like dashboards, insights, and more',
    <>
        <em>In Insights:</em> Edit the currently-viewed insight
    </>,
    <>
        <em>In SQL editor:</em> Write and tweak HogQL queries
    </>,
    <>
        <em>In Session replay:</em> Search session recordings
    </>,
    <>
        <em>In Surveys:</em> Create surveys
    </>,
    <>
        <em>In Data pipelines:</em> Set up pipeline transformations and filters, using Hog
    </>,
] as const

export const MAX_CANNOT = [
    'Access your infrastructure, source code, or third‑party tools',
    'Browse the web beyond PostHog documentation',
    'See data outside this PostHog project',
    'Guarantee correctness of the queries created',
    'Order tungsten cubes',
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

interface ToolsDisplayProps {
    isFloating?: boolean
    tools: ToolDefinition[]
    bottomActions?: ReactNode
}

const ToolsDisplay: React.FC<ToolsDisplayProps> = ({ isFloating, tools, bottomActions }) => {
    const toolsContainerRef = useRef<HTMLDivElement>(null)
    const toolsRef = useRef<HTMLElement[]>([])
    const [firstToolOverflowing, setFirstToolOverflowing] = useState<AssistantContextualTool | null>(null)

    useResizeObserver({
        ref: toolsContainerRef,
        onResize: () => {
            let foundOverflow = false
            for (let i = 0; i < toolsRef.current.length; i++) {
                const toolEl = toolsRef.current[i]
                if (toolEl) {
                    const rightOverflow =
                        toolEl.getBoundingClientRect().right - toolEl.parentElement!.getBoundingClientRect().right
                    // Items other than the last one need 60px free space to the right to safely show "+ n more"
                    const freeSpaceRequirementPx = i < toolsRef.current.length - 1 ? 60 : 0
                    if (rightOverflow > -freeSpaceRequirementPx) {
                        setFirstToolOverflowing(tools[tools.length - i - 1].name)
                        foundOverflow = true
                        break
                    }
                }
            }
            if (!foundOverflow) {
                setFirstToolOverflowing(null)
            }
        },
    })

    // We show the tools reversed, so the ones registered last (scene-specific) are shown first
    const toolsInReverse = tools.toReversed()
    const toolsHidden = firstToolOverflowing
        ? toolsInReverse
              .slice(toolsInReverse.findIndex((tool) => tool.name === firstToolOverflowing))
              .map((tool) => tool.name)
        : []

    return (
        <div ref={toolsContainerRef} className="flex items-center w-full gap-1 justify-center cursor-help">
            <Tooltip
                placement="bottom-end"
                arrowOffset={8 /* 8px from right edge to align with the info icon */}
                title={
                    <>
                        <div className="mb-2">
                            <div className="font-semibold mb-0.5">Max can:</div>
                            <ul className="space-y-0.5 text-sm">
                                {MAX_CAN.map((item, index) => (
                                    <li key={index} className="flex items-center">
                                        <IconCheck className="text-base text-success shrink-0 ml-1 mr-2" />
                                        <span>{item}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                        <div>
                            <div className="font-semibold mb-0.5">Max can't (yet):</div>
                            <ul className="space-y-0.5 text-sm">
                                {MAX_CANNOT.map((item, index) => (
                                    <li key={index} className="flex items-center">
                                        <IconX className="text-base text-danger shrink-0 ml-1 mr-2" />
                                        <span>{item}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    </>
                }
            >
                <div
                    className={clsx(
                        'relative flex items-center text-xs font-medium justify-between gap-1 px-1',
                        !isFloating
                            ? 'w-[calc(100%-1rem)] py-0.75 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)]'
                            : `w-full pb-1`
                    )}
                >
                    <div className="w-full flex items-center gap-1">
                        <span className="shrink-0">Tools available:</span>
                        {toolsInReverse.map((tool, index) => (
                            <React.Fragment key={tool.name}>
                                <span
                                    ref={(e) => e && (toolsRef.current[index] = e)}
                                    className="relative flex-shrink-0"
                                >
                                    <ToolPill tool={tool} hidden={toolsHidden.includes(tool.name)} />
                                    {tool.name === firstToolOverflowing && (
                                        <span className="absolute left-0 top-0 bottom-0 text-xs text-muted-foreground flex items-center gap-1">
                                            + {toolsHidden.length} more
                                        </span>
                                    )}
                                </span>
                            </React.Fragment>
                        ))}
                    </div>
                    <IconInfo className="text-sm" />
                </div>
            </Tooltip>
            {bottomActions && <div className="ml-auto">{bottomActions}</div>}
        </div>
    )
}

function ToolPill({ tool, hidden }: { tool: ToolDefinition; hidden: boolean }): JSX.Element {
    return (
        <em
            className={clsx(
                // We're using --color-posthog-3000-300 instead of border-primary (--color-posthog-3000-200)
                // or border-secondary (--color-posthog-3000-400) because the former is almost invisible here, and the latter too distinct
                'relative inline-flex items-center gap-1 border border-[var(--color-posthog-3000-300)] border-dashed rounded-sm pl-0.5 pr-1',
                hidden && 'invisible'
            )}
        >
            <span className="text-sm">{tool.icon || <IconWrench />}</span>
            {tool.displayName}
        </em>
    )
}
