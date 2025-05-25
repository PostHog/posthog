import './QuestionInput.scss'

import { IconArrowRight, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'
import { ToggleGroup, ToggleGroupItem } from '@radix-ui/react-toggle-group'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconTools } from 'lib/lemon-ui/icons'
import { useEffect, useRef } from 'react'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'

interface QuestionInputProps {
    isFloating?: boolean
}

export function QuestionInput({ isFloating }: QuestionInputProps): JSX.Element {
    const { tools } = useValues(maxGlobalLogic)
    const { question, threadLoading, inputDisabled, submissionDisabledReason, focusCounter, activeSuggestionGroup } =
        useValues(maxLogic)
    const { askMax, setQuestion, stopGeneration, focusInput, setActiveGroup } = useActions(maxLogic)

    const textAreaRef = useRef<HTMLTextAreaElement | null>(null)
    const focusElementRef = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        if (threadLoading) {
            textAreaRef.current?.focus() // Focus after submit
        }
    }, [threadLoading])

    useEffect(() => {
        if (textAreaRef.current) {
            textAreaRef.current.focus()
            textAreaRef.current.setSelectionRange(textAreaRef.current.value.length, textAreaRef.current.value.length)
        }
    }, [focusCounter]) // Update focus when focusCounter changes

    useEffect(() => {
        if (focusElementRef.current && activeSuggestionGroup) {
            focusElementRef.current.focus()
        }
    }, [activeSuggestionGroup])

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
                <div className="relative w-full">
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
                        disabled={inputDisabled}
                        minRows={1}
                        maxRows={10}
                        className={clsx('p-3 pr-12', isFloating && 'border-primary')}
                    />
                    <div className="absolute flex items-center right-2 bottom-[7px]">
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
                    {activeSuggestionGroup && !isFloating && (
                        <ToggleGroup
                            type="single"
                            className="absolute inset-x-2 top-full grid auto-rows-auto p-1 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)] z-10"
                            ref={focusElementRef}
                            onValueChange={(index) => {
                                const suggestion = activeSuggestionGroup.suggestions[Number(index)]
                                if (!suggestion) {
                                    return
                                }

                                if (suggestion.content) {
                                    // Content requires to write something to continue
                                    setQuestion(suggestion.content)
                                    focusInput()
                                } else {
                                    // Otherwise, just launch the generation
                                    askMax(suggestion.label)
                                }

                                // Close suggestions after asking
                                setActiveGroup(null)
                            }}
                        >
                            {activeSuggestionGroup.suggestions.map((suggestion, index) => (
                                <ToggleGroupItem
                                    key={suggestion.label}
                                    value={index.toString()}
                                    tabIndex={0}
                                    aria-label={`Select suggestion: ${suggestion.label}`}
                                    asChild
                                >
                                    <LemonButton
                                        className="QuestionSuggestion text-left"
                                        role="button"
                                        style={{ '--index': index } as React.CSSProperties}
                                        size="small"
                                        type="tertiary"
                                        fullWidth
                                    >
                                        <span className="font-normal ">{suggestion.label}</span>
                                    </LemonButton>
                                </ToggleGroupItem>
                            ))}
                        </ToggleGroup>
                    )}
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
}
