import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { maxLogic } from './maxLogic'

export function QuestionInput(): JSX.Element {
    const { question, thread, threadLoading } = useValues(maxLogic)
    const { askMax, setQuestion } = useActions(maxLogic)

    const textAreaRef = useRef<HTMLTextAreaElement | null>(null)

    const isFloating = thread.length > 0

    useEffect(() => {
        if (!threadLoading) {
            textAreaRef.current?.focus() // Auto focus, both on mount and when Max finishes thinking
        }
    }, [threadLoading])

    return (
        <div
            className={clsx(
                'w-full',
                !isFloating
                    ? 'w-[min(40rem,100%)] relative'
                    : 'max-w-200 sticky z-10 self-center p-1 mx-3 mb-3 bottom-3 border border-[var(--glass-border-3000)] rounded-[0.625rem] backdrop-blur bg-[var(--glass-bg-3000)]'
            )}
        >
            <LemonTextArea
                ref={textAreaRef}
                value={question}
                onChange={(value) => setQuestion(value)}
                placeholder={threadLoading ? 'Thinking…' : isFloating ? 'Ask follow-up' : 'Ask away'}
                onPressEnter={() => {
                    if (question) {
                        askMax(question)
                    }
                }}
                disabled={threadLoading}
                minRows={1}
                maxRows={10}
                className={clsx('p-3', isFloating && 'border-border-bold')}
            />
            <div className={clsx('absolute top-0 bottom-0 flex items-center', isFloating ? 'right-3' : 'right-2')}>
                <LemonButton
                    type={isFloating && !question ? 'secondary' : 'primary'}
                    onClick={() => askMax(question)}
                    tooltip="Let's go!"
                    disabledReason={!question ? 'I need some input first' : threadLoading ? 'Thinking…' : undefined}
                    size="small"
                    icon={<IconArrowRight />}
                />
            </div>
        </div>
    )
}
