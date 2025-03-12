import { IconArrowRight, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { cn } from 'lib/utils/css-classes'
import { useEffect, useRef } from 'react'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { maxLogic } from './maxLogic'

export function QuestionInput(): JSX.Element {
    const { question, threadGrouped, threadLoading, inputDisabled, submissionDisabledReason } = useValues(maxLogic)
    const { askMax, setQuestion, stopGeneration } = useActions(maxLogic)

    const textAreaRef = useRef<HTMLTextAreaElement | null>(null)

    const isFloating = threadGrouped.length > 0

    useEffect(() => {
        if (threadLoading) {
            textAreaRef.current?.focus() // Focus after submit
        }
    }, [threadLoading])

    return (
        <div
            className={cn(
                'px-3',
                !isFloating ? 'relative w-[min(44rem,100%)]' : 'sticky bottom-0 z-10 w-full max-w-[45rem] self-center'
            )}
        >
            <div
                className={cn(
                    'flex flex-col items-center gap-2',
                    isFloating &&
                        'p-1 mb-3 bottom-3 border border-[var(--border-primary)] rounded-lg backdrop-blur-sm bg-[var(--glass-bg-3000)]'
                )}
            >
                <LemonTextArea
                    ref={textAreaRef}
                    value={question}
                    onChange={(value) => setQuestion(value)}
                    placeholder={threadLoading ? 'Thinking…' : isFloating ? 'Ask follow-up' : 'Ask away'}
                    onPressEnter={() => {
                        if (question && !submissionDisabledReason && !threadLoading) {
                            askMax(question)
                        }
                    }}
                    autoFocus
                    disabled={inputDisabled}
                    minRows={1}
                    maxRows={10}
                    className={cn('p-3 pr-12', isFloating && 'border-primary')}
                />
                <div
                    className={cn(
                        'absolute flex items-center',
                        isFloating ? 'right-3 bottom-[11px]' : 'right-5 bottom-[7px]'
                    )}
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
                        disabledReason={submissionDisabledReason}
                        size="small"
                        icon={threadLoading ? <IconStopFilled /> : <IconArrowRight />}
                    />
                </div>
            </div>
        </div>
    )
}
