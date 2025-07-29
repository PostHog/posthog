import './QuestionInput.scss'

import { LemonButton } from '@posthog/lemon-ui'
import { ToggleGroup, ToggleGroupItem } from '@radix-ui/react-toggle-group'

import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'
import { CSSTransition } from 'react-transition-group'

import { maxLogic, SuggestionGroup } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { checkSuggestionRequiresUserInput, formatSuggestion, stripSuggestionPlaceholders } from '../utils'
import { QuestionInput } from './QuestionInput'

export function SidebarQuestionInput({ isSticky = false }: { isSticky?: boolean }): JSX.Element {
    const { focusCounter, threadVisible } = useValues(maxLogic)
    const { threadLoading } = useValues(maxThreadLogic)

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
        <QuestionInput
            isSticky={isSticky}
            textAreaRef={textAreaRef}
            containerClassName="px-3 mx-auto self-center pb-1"
            isFloating={threadVisible}
            isThreadVisible={threadVisible}
        >
            <SuggestionsList />
        </QuestionInput>
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

    const suggestionGroup = activeSuggestionGroup || previousSuggestionGroup.current

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
                {suggestionGroup?.suggestions.map((suggestion, index) => (
                    <ToggleGroupItem
                        key={suggestion.content}
                        value={index.toString()}
                        tabIndex={0}
                        aria-label={`Select suggestion: ${suggestion.content}`}
                        asChild
                    >
                        <LemonButton
                            className="QuestionInput__QuestionSuggestion text-left"
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
