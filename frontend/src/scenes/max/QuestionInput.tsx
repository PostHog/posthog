import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { maxLogic } from './maxLogic'

export function QuestionInput(): JSX.Element {
    const { question, threadGrouped, threadLoading, inputDisabled, submissionDisabledReason } = useValues(maxLogic)
    const { askMax, setQuestion } = useActions(maxLogic)

    const textAreaRef = useRef<HTMLTextAreaElement | null>(null)

    const isFloating = threadGrouped.length > 0

    useEffect(() => {
        if (threadLoading) {
            textAreaRef.current?.focus() // Focus after submit
        }
    }, [threadLoading])

    return (
        <div
            className={clsx(
                'px-3',
                !isFloating ? 'relative w-[min(44rem,100%)]' : 'sticky bottom-0 z-10 w-full max-w-[45rem] self-center'
            )}
        >
            <div
                className={clsx(
                    'flex flex-col items-center gap-2',
                    isFloating &&
                        'p-1 mb-3 bottom-3 border border-[var(--border-primary)] rounded-lg backdrop-blur bg-[var(--glass-bg-3000)]'
                )}
            >
                <LemonTextArea
                    ref={textAreaRef}
                    value={question}
                    onChange={(value) => setQuestion(value)}
                    placeholder={threadLoading ? 'Thinking…' : isFloating ? 'Ask follow-up' : 'Ask away'}
                    onPressEnter={() => {
                        if (question && !submissionDisabledReason) {
                            askMax(question)
                        }
                    }}
                    autoFocus
                    disabled={inputDisabled}
                    minRows={1}
                    maxRows={10}
                    className={clsx('p-3 pr-12', isFloating && 'border-border-bold')}
                />
                <div
                    className={clsx(
                        'absolute flex items-center',
                        isFloating ? 'right-3 bottom-[11px]' : 'right-5 bottom-[7px]'
                    )}
                >
                    <LemonButton
                        type={isFloating && !question ? 'secondary' : 'primary'}
                        onClick={() => askMax(question)}
                        tooltip="Let's go!"
                        disabledReason={submissionDisabledReason}
                        size="small"
                        icon={<IconArrowRight />}
                    />
                </div>
            </div>
        </div>
    )
}
