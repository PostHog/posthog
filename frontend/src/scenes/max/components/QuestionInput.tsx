import { offset } from '@floating-ui/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'
import React from 'react'

import { IconArrowRight, IconStopFilled, IconWrench } from '@posthog/icons'
import { LemonButton, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { ContextDisplay } from '../Context'
import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'

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
    const { tools, dataProcessingAccepted } = useValues(maxGlobalLogic)
    const { question } = useValues(maxLogic)
    const { setQuestion } = useActions(maxLogic)
    const { threadLoading, inputDisabled, submissionDisabledReason } = useValues(maxThreadLogic)
    const { askMax, stopGeneration, completeThreadGeneration } = useActions(maxThreadLogic)

    return (
        <div
            className={clsx(
                containerClassName,
                !isSticky && !isFloating
                    ? 'w-[min(40rem,100%)] px-3'
                    : 'sticky bottom-0 z-10 w-full max-w-[45.25rem] self-center'
            )}
            ref={ref}
        >
            <div
                className={clsx(
                    'flex flex-col items-center',
                    isSticky &&
                        'mb-2 rounded-lg border border-[var(--border-primary)] bg-[var(--glass-bg-3000)] backdrop-blur-sm'
                )}
            >
                <div className="relative flex w-full flex-col">
                    {children}
                    <div
                        className={clsx(
                            'flex flex-col',
                            'rounded-[var(--radius)] border border-[var(--border-primary)]',
                            'bg-[var(--bg-fill-input)]',
                            'focus-within:border-[var(--border-bold)] hover:border-[var(--border-bold)]',
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
                                <div className="mr-1 mt-1 flex h-full items-start gap-1">{topActions}</div>
                            </div>
                        ) : (
                            <ContextDisplay size={contextDisplaySize} />
                        )}
                        <LemonTextArea
                            ref={textAreaRef}
                            value={question}
                            onChange={(value) => setQuestion(value)}
                            placeholder={
                                threadLoading ? 'Thinking…' : isFloating ? placeholder || 'Ask follow-up' : 'Ask away'
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
                            className="min-h-0 !border-none !bg-transparent py-2.5 pl-2.5 pr-12"
                        />
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
                                icon={threadLoading ? <IconStopFilled /> : <IconArrowRight />}
                            />
                        </AIConsentPopoverWrapper>
                    </div>
                </div>
                <div className="flex w-full items-center justify-between gap-1">
                    {tools.length > 0 && (
                        <div
                            className={clsx(
                                'flex cursor-default flex-wrap gap-x-1 gap-y-0.5 whitespace-nowrap px-1.5 text-xs font-medium',
                                !isFloating
                                    ? 'w-[calc(100%-1rem)] rounded-b border-x border-b bg-[var(--glass-bg-3000)] py-1 backdrop-blur-sm'
                                    : `w-full pb-1`
                            )}
                        >
                            <span>Tools here:</span>
                            {tools.map((tool) => (
                                <Tooltip key={tool.name} title={tool.description}>
                                    <i className="flex cursor-help items-center gap-1">
                                        {tool.icon || <IconWrench />}
                                        {tool.displayName}
                                    </i>
                                </Tooltip>
                            ))}
                        </div>
                    )}
                    <div className="ml-auto">{bottomActions}</div>
                </div>
            </div>
        </div>
    )
})
