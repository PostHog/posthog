import './QuestionInput.scss'

import { ToggleGroup, ToggleGroupItem } from '@radix-ui/react-toggle-group'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'
import { CSSTransition } from 'react-transition-group'

import { LemonButton } from '@posthog/lemon-ui'

import { SuggestionGroup, maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { checkSuggestionRequiresUserInput, formatSuggestion, stripSuggestionPlaceholders } from '../utils'
import { InputFormArea } from './InputFormArea'
import { QuestionInput } from './QuestionInput'

export function SidebarQuestionInput({ isSticky = false }: { isSticky?: boolean }): JSX.Element {
    const { focusCounter, threadVisible } = useValues(maxLogic)
    // Use raw state values instead of selector to ensure re-renders on state changes
    const {
        threadLoading,
        activeMultiQuestionForm,
        pendingApprovalProposalId,
        pendingApprovalsData,
        resolvedApprovalStatuses,
    } = useValues(maxThreadLogic)

    // Check if there's a pending (not yet resolved) approval to show
    const hasApprovalToShow = useMemo(() => {
        if (!pendingApprovalProposalId) {
            return false
        }
        // Don't show if already resolved - resolved approvals appear as summaries in the chat thread
        if (resolvedApprovalStatuses[pendingApprovalProposalId]) {
            return false
        }
        return !!pendingApprovalsData[pendingApprovalProposalId]
    }, [pendingApprovalProposalId, pendingApprovalsData, resolvedApprovalStatuses])

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

    // Show form area directly when there's a pending form/approval (even if showInput is false)
    if (activeMultiQuestionForm || hasApprovalToShow) {
        return (
            <div className="w-full max-w-180 self-center px-3 mx-auto pb-1 bg-[var(--scene-layout-background)]/50 backdrop-blur-sm">
                <div className="border border-primary rounded-lg bg-surface-primary">
                    <InputFormArea />
                </div>
                <p className="w-full flex text-xs text-muted mt-1">
                    <span className="mx-auto">PostHog AI can make mistakes. Please double-check responses.</span>
                </p>
            </div>
        )
    }

    return (
        <QuestionInput
            isSticky={isSticky}
            textAreaRef={textAreaRef}
            containerClassName="px-3 mx-auto self-center pb-1 backdrop-blur-sm z-50"
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
                className="QuestionInput__SuggestionsList absolute inset-x-2 top-full grid auto-rows-auto p-1 border-x border-b rounded-b-lg bg-surface-primary z-10"
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
                        setQuestion(suggestion.content)
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
