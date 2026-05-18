import './QuestionInput.scss'

import { ToggleGroup, ToggleGroupItem } from '@radix-ui/react-toggle-group'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { useAnimatedPresence } from 'lib/hooks/useAnimatedPresence'
import { cn } from 'lib/utils/css-classes'

import { SuggestionGroup, maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { InputFormArea } from './InputFormArea'
import { QuestionInput } from './QuestionInput'

export function SidebarQuestionInput({
    isSticky = false,
    sidePanel = false,
}: {
    isSticky?: boolean
    sidePanel?: boolean
}): JSX.Element {
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
            <div className="w-full max-w-180 self-center px-3 mx-auto bg-[var(--scene-layout-background)]/50 backdrop-blur-sm">
                <div className="border border-primary rounded-lg bg-surface-primary">
                    <InputFormArea />
                </div>
            </div>
        )
    }

    return (
        <QuestionInput
            isSticky={isSticky}
            textAreaRef={textAreaRef}
            containerClassName={cn('w-full px-3 mx-auto self-center backdrop-blur-sm z-50', sidePanel && 'px-0')}
            isThreadVisible={threadVisible}
        >
            <SuggestionsList />
        </QuestionInput>
    )
}

function SuggestionsList(): JSX.Element | null {
    const focusElementRef = useRef<HTMLDivElement | null>(null)
    const previousSuggestionGroup = useRef<SuggestionGroup | null>(null)

    const { setQuestion, focusInput, setActiveGroup } = useActions(maxLogic)
    const { activeSuggestionGroup } = useValues(maxLogic)
    const { askMax } = useActions(maxThreadLogic)

    const { rendered, shown } = useAnimatedPresence(!!activeSuggestionGroup, 150)

    useEffect(() => {
        if (focusElementRef.current && activeSuggestionGroup) {
            focusElementRef.current.focus()
        }
        previousSuggestionGroup.current = activeSuggestionGroup
    }, [activeSuggestionGroup, rendered])

    const suggestionGroup = activeSuggestionGroup || previousSuggestionGroup.current

    if (!rendered) {
        return null
    }

    return (
        <ToggleGroup
            ref={focusElementRef}
            type="single"
            className={clsx(
                'QuestionInput__SuggestionsList absolute inset-x-2 top-full grid auto-rows-auto p-1 border-x border-b rounded-b-lg bg-surface-primary z-10',
                shown && 'QuestionInput__SuggestionsList--visible'
            )}
            onValueChange={(index) => {
                const suggestion = activeSuggestionGroup?.suggestions[Number(index)]
                if (!suggestion) {
                    return
                }

                if (suggestion.requiresUserInput) {
                    // Content requires to write something to continue
                    setQuestion(suggestion.content)
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
                        <span className="font-normal">{suggestion.content}</span>
                    </LemonButton>
                </ToggleGroupItem>
            ))}
        </ToggleGroup>
    )
}
