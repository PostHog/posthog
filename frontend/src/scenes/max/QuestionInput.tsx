import './QuestionInput.scss'

import { IconArrowRight, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'
import { ToggleGroup, ToggleGroupItem } from '@radix-ui/react-toggle-group'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconTools } from 'lib/lemon-ui/icons'
import { useEffect, useRef } from 'react'
import { CSSTransition } from 'react-transition-group'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { ContextDisplay } from './ContextDisplay'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic, SuggestionGroup } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'
import { checkSuggestionRequiresUserInput, formatSuggestion, stripSuggestionPlaceholders } from './utils'

interface QuestionInputProps {
    isFloating?: boolean
}

export function QuestionInput({ isFloating }: QuestionInputProps): JSX.Element {
    const { tools } = useValues(maxGlobalLogic)

    const { question, focusCounter } = useValues(maxLogic)
    const { setQuestion } = useActions(maxLogic)

    const { threadLoading, inputDisabled, submissionDisabledReason } = useValues(maxThreadLogic)
    const { askMax, stopGeneration } = useActions(maxThreadLogic)

    const textAreaRef = useRef<HTMLTextAreaElement | null>(null)

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
                    <div
                        className={clsx(
                            'flex flex-col',
                            'border border-[var(--border-primary)] rounded-[var(--radius)]',
                            'bg-[var(--bg-fill-input)] cursor-text',
                            'hover:border-[var(--border-bold)] focus-within:border-[var(--border-bold)]',
                            isFloating && 'border-primary'
                        )}
                        onClick={(e) => {
                            // If user clicks anywhere with the area with a hover border, activate input - except on button clicks
                            if (!(e.target as HTMLElement).closest('button')) {
                                textAreaRef.current?.focus()
                            }
                        }}
                    >
                        <ContextDisplay />
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
                            className={clsx('!border-none !bg-transparent min-h-0 py-2.5 pl-2.5 pr-12')}
                        />
                    </div>
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
                    {!isFloating && <SuggestionsList />}
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

function SuggestionsList(): JSX.Element {
    const focusElementRef = useRef<HTMLDivElement | null>(null)
    const previousSuggestionGroup = useRef<SuggestionGroup | null>(null)

    const { setQuestion, focusInput, setActiveGroup } = useActions(maxLogic)
    const { activeSuggestionGroup } = useValues(maxLogic)
    const { askMax } = useActions(maxThreadLogic)

    useEffect(() => {
        if (focusElementRef.current && activeSuggestionGroup) {
            focusElementRef.current.focus()
        }
        previousSuggestionGroup.current = activeSuggestionGroup
    }, [activeSuggestionGroup])

    const memoizedSuggestion = activeSuggestionGroup || previousSuggestionGroup.current

    return (
        <CSSTransition
            in={!!activeSuggestionGroup}
            timeout={150}
            classNames="QuestionInput__SuggestionsList"
            mountOnEnter
            unmountOnExit
            nodeRef={focusElementRef}
        >
            <ToggleGroup
                ref={focusElementRef}
                type="single"
                className="QuestionInput__SuggestionsList absolute inset-x-2 top-full grid auto-rows-auto p-1 border-x border-b rounded-b-lg backdrop-blur-sm bg-[var(--glass-bg-3000)] z-10"
                onValueChange={(index) => {
                    const suggestion = activeSuggestionGroup?.suggestions[Number(index)]
                    if (!suggestion) {
                        return
                    }

                    if (checkSuggestionRequiresUserInput(suggestion.content)) {
                        // Content requires to write something to continue
                        setQuestion(stripSuggestionPlaceholders(suggestion.content))
                        focusInput()
                    } else {
                        // Otherwise, just launch the generation
                        askMax(suggestion.content)
                    }

                    // Close suggestions after asking
                    setActiveGroup(null)
                }}
            >
                {memoizedSuggestion?.suggestions.map((suggestion, index) => (
                    <ToggleGroupItem
                        key={suggestion.content}
                        value={index.toString()}
                        tabIndex={0}
                        aria-label={`Select suggestion: ${suggestion.content}`}
                        asChild
                    >
                        <LemonButton
                            className="QuestionInput__QuestionSuggestion text-left"
                            role="button"
                            style={{ '--index': index } as React.CSSProperties}
                            size="small"
                            type="tertiary"
                            fullWidth
                        >
                            <span className="font-normal">{formatSuggestion(suggestion.content)}</span>
                        </LemonButton>
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </CSSTransition>
    )
}
