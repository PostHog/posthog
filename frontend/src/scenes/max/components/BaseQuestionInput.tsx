import { offset } from '@floating-ui/react'
import { IconArrowRight, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconTools } from 'lib/lemon-ui/icons'
import React, { ReactNode } from 'react'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { ContextDisplay } from './ContextDisplay'

interface BaseQuestionInputProps {
    isFloating?: boolean
    placeholder?: string
    children?: ReactNode
    contextDisplaySize?: 'small' | 'default'
    topActions?: ReactNode
    textAreaRef?: React.RefObject<HTMLTextAreaElement>
    containerClassName?: string
    wrapperClassName?: string
}

export const BaseQuestionInput = React.forwardRef<HTMLDivElement, BaseQuestionInputProps>(function BaseQuestionInput(
    {
        isFloating,
        placeholder,
        children,
        contextDisplaySize,
        topActions,
        textAreaRef,
        containerClassName,
        wrapperClassName,
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
                containerClassName ||
                    (!isFloating
                        ? 'px-3 w-[min(44rem,100%)]'
                        : 'px-1 sticky bottom-0 z-10 w-full max-w-[45rem] self-center')
            )}
            ref={ref}
        >
            <div
                className={clsx(
                    wrapperClassName ||
                        clsx(
                            'flex flex-col items-center',
                            isFloating &&
                                'p-1 mb-2 border border-[var(--border-primary)] rounded-lg backdrop-blur-sm bg-[var(--glass-bg-3000)]'
                        )
                )}
            >
                <div className="relative w-full flex flex-col gap-1">
                    {children}
                    <div
                        className={clsx(
                            'flex flex-col',
                            'border border-[var(--border-primary)] rounded-[var(--radius)]',
                            'bg-[var(--bg-fill-input)]',
                            'hover:border-[var(--border-bold)] focus-within:border-[var(--border-bold)]',
                            isFloating && 'border-primary'
                        )}
                    >
                        {topActions ? (
                            <div className="flex items-start justify-between">
                                <ContextDisplay size={contextDisplaySize} />
                                <div className="flex items-start gap-1 h-full mt-1 mr-1">{topActions}</div>
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
                                    askMax(question)
                                }
                            }}
                            disabled={inputDisabled}
                            minRows={1}
                            maxRows={10}
                            className={clsx(
                                '!border-none !bg-transparent min-h-0 py-2.5 pl-2.5',
                                isFloating ? 'pr-20' : 'pr-12'
                            )}
                        />
                    </div>
                    <div className="absolute flex items-center right-2 bottom-[7px]">
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
                                        ? 'Pending data processing approval'
                                        : submissionDisabledReason
                                }
                                size="small"
                                icon={threadLoading ? <IconStopFilled /> : <IconArrowRight />}
                            />
                        </AIConsentPopoverWrapper>
                    </div>
                </div>
                {tools.length > 0 && (
                    <div
                        className={clsx(
                            'flex gap-1 text-xs font-medium cursor-default px-1.5',
                            !isFloating
                                ? 'w-[calc(100%-1rem)] py-1 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)]'
                                : 'w-full pt-1'
                        )}
                    >
                        <span>Tools in context:</span>
                        {tools.map((tool) => (
                            <i key={tool.name} className="flex items-center gap-1">
                                <IconTools />
                                {tool.displayName}
                            </i>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
})
