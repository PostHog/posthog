import { IconArrowRight, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconTools } from 'lib/lemon-ui/icons'
import { useEffect, useRef } from 'react'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'

interface QuestionInputComponentProps {
    value: string
    onChange: (value: string) => void
    onSubmit: () => void
    onStop?: () => void
    isLoading?: boolean
    isFloating?: boolean
    disabled?: boolean
    disabledReason?: string
    placeholder?: string
    autoFocus?: boolean
}

export function QuestionInputComponent({
    value,
    onChange,
    onSubmit,
    onStop,
    isLoading = false,
    isFloating = false,
    disabled = false,
    disabledReason,
    placeholder = 'Ask away',
    autoFocus = false,
}: QuestionInputComponentProps): JSX.Element {
    const textAreaRef = useRef<HTMLTextAreaElement | null>(null)

    useEffect(() => {
        if (isLoading) {
            textAreaRef.current?.focus()
        }
    }, [isLoading])

    useEffect(() => {
        if (autoFocus && textAreaRef.current) {
            textAreaRef.current.focus()
            textAreaRef.current.setSelectionRange(textAreaRef.current.value.length, textAreaRef.current.value.length)
        }
    }, [autoFocus])

    return (
        <div className="relative w-full">
            <LemonTextArea
                ref={textAreaRef}
                value={value}
                onChange={onChange}
                placeholder={isLoading ? 'Thinking…' : isFloating ? 'Ask follow-up' : placeholder}
                onPressEnter={() => {
                    if (value && !disabledReason && !isLoading) {
                        onSubmit()
                    }
                }}
                disabled={disabled}
                minRows={1}
                maxRows={10}
                className={clsx('p-3 pr-12', isFloating && 'border-primary')}
            />
            <div className="absolute flex items-center right-3 bottom-[7px]">
                <LemonButton
                    type={(isFloating && !value) || isLoading ? 'secondary' : 'primary'}
                    onClick={() => {
                        if (isLoading) {
                            onStop?.()
                        } else {
                            onSubmit()
                        }
                    }}
                    tooltip={
                        isLoading ? (
                            "Let's bail"
                        ) : (
                            <>
                                Let's go! <KeyboardShortcut enter />
                            </>
                        )
                    }
                    disabledReason={disabledReason}
                    size="small"
                    icon={isLoading ? <IconStopFilled /> : <IconArrowRight />}
                />
            </div>
        </div>
    )
}

export function QuestionInput(): JSX.Element {
    const { tools } = useValues(maxGlobalLogic)
    const { question, threadGrouped, threadLoading, inputDisabled, submissionDisabledReason } = useValues(maxLogic)
    const { askMax, setQuestion, stopGeneration } = useActions(maxLogic)

    const isFloating = threadGrouped.length > 0

    return (
        <div
            className={clsx(
                'px-3',
                !isFloating ? 'w-[min(44rem,100%)]' : 'sticky bottom-0 z-10 w-full max-w-[45rem] self-center'
            )}
        >
            <div
                className={clsx(
                    'flex flex-col items-center',
                    isFloating &&
                        'p-1 border border-[var(--border-primary)] rounded-lg backdrop-blur-sm bg-[var(--glass-bg-3000)]',
                    isFloating && (tools.length > 0 ? 'mb-1.5' : 'mb-3')
                )}
            >
                <QuestionInputComponent
                    value={question}
                    onChange={setQuestion}
                    onSubmit={() => askMax(question)}
                    onStop={stopGeneration}
                    isLoading={threadLoading}
                    isFloating={isFloating}
                    disabled={inputDisabled}
                    disabledReason={submissionDisabledReason}
                    autoFocus={true}
                />
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
}
