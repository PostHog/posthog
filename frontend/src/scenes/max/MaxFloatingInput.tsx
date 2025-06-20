import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useRef } from 'react'
import React from 'react'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'

import { BaseQuestionInput } from './components/BaseQuestionInput'
import { FloatingInputActions } from './components/FloatingInputActions'
import { HedgehogAvatar } from './components/HedgehogAvatar'
import { SuggestionsDisplay } from './components/SuggestionsDisplay'
import { ThreadAutoScroller } from './components/ThreadAutoScroller'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { maxThreadLogic, MaxThreadLogicProps } from './maxThreadLogic'
import { Thread } from './Thread'

interface MaxQuestionInputProps {
    placeholder?: string
    suggestions?: React.ReactNode
    hideTopActions?: boolean
}

const MaxQuestionInput = React.forwardRef<HTMLDivElement, MaxQuestionInputProps>(function MaxQuestionInput(
    { placeholder, suggestions, hideTopActions = false }: MaxQuestionInputProps,
    ref
) {
    const { focusCounter } = useValues(maxLogic)
    const { showSuggestions } = useValues(maxLogic)
    const { setShowSuggestions } = useActions(maxLogic)
    const { setIsFloatingMaxExpanded } = useActions(maxGlobalLogic)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)

    const handleCollapse = (): void => {
        setShowSuggestions(false)
        setIsFloatingMaxExpanded(false)
    }

    useEffect(() => {
        if (textAreaRef.current) {
            textAreaRef.current.focus()
            textAreaRef.current.setSelectionRange(textAreaRef.current.value.length, textAreaRef.current.value.length)
        }
    }, [focusCounter])

    return (
        <BaseQuestionInput
            ref={ref}
            isFloating={true}
            placeholder={placeholder}
            contextDisplaySize="small"
            showTopActions={!hideTopActions}
            textAreaRef={textAreaRef}
            topActions={
                !hideTopActions ? (
                    <FloatingInputActions
                        showSuggestions={showSuggestions}
                        onCollapse={handleCollapse}
                        isThreadVisible={false}
                    />
                ) : undefined
            }
            containerClassName="sticky bottom-0 z-10 w-full max-w-[45rem] self-center"
        >
            {suggestions}
        </BaseQuestionInput>
    )
})

function MaxFloatingInputContent(): JSX.Element {
    const { dataProcessingAccepted, showSuggestions, threadVisible } = useValues(maxLogic)
    const { setShowSuggestions, setActiveGroup } = useActions(maxLogic)
    const { isFloatingMaxExpanded } = useValues(maxGlobalLogic)
    const { setIsFloatingMaxExpanded } = useActions(maxGlobalLogic)
    const { startNewConversation } = useActions(maxLogic)
    const { conversation } = useValues(maxThreadLogic)

    const handleExpand = (): void => {
        setIsFloatingMaxExpanded(true)
    }

    const handleDismiss = (): void => {
        setActiveGroup(null)
        setShowSuggestions(false)
    }

    const handleCollapse = (): void => {
        setActiveGroup(null)
        setShowSuggestions(false)
        setIsFloatingMaxExpanded(false)
        startNewConversation()
    }

    if (!isFloatingMaxExpanded) {
        return <HedgehogAvatar onExpand={handleExpand} isExpanded={isFloatingMaxExpanded} />
    }

    return (
        <div
            className="relative flex flex-col"
            onBlur={(e) => {
                // Only lose focus if clicking outside the entire container
                if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                    handleDismiss()
                }
            }}
        >
            <MaxQuestionInput
                placeholder="Ask Max AI"
                hideTopActions={threadVisible}
                suggestions={
                    showSuggestions ? (
                        <SuggestionsDisplay
                            compact
                            showSuggestions={showSuggestions}
                            dataProcessingAccepted={dataProcessingAccepted}
                            type="tertiary"
                        />
                    ) : threadVisible ? (
                        <>
                            <div className="flex items-center justify-between px-3 py-2 border-b border-border">
                                <div className="text-xs font-medium text-muted">{conversation?.title}</div>
                                <div className="flex items-center gap-1">
                                    <FloatingInputActions
                                        showSuggestions={showSuggestions}
                                        onCollapse={handleCollapse}
                                        isThreadVisible={true}
                                    />
                                </div>
                            </div>
                            <div className="max-h-96 overflow-y-auto">
                                <ThreadAutoScroller>
                                    <Thread className="p-1" />
                                </ThreadAutoScroller>
                            </div>
                        </>
                    ) : null
                }
            />
        </div>
    )
}

export function MaxFloatingInput(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { sidePanelOpen } = useValues(sidePanelLogic)
    const { isFloatingMaxExpanded } = useValues(maxGlobalLogic)

    const { threadLogicKey, conversation } = useValues(maxLogic)

    if (!featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG] || !featureFlags[FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG]) {
        return null
    }

    if (sidePanelOpen) {
        return null
    }

    const threadProps: MaxThreadLogicProps = {
        conversationId: threadLogicKey,
        conversation,
    }

    return (
        // `right:` gets 1px removed to account for border
        <div
            className={clsx(
                'fixed bottom-0 z-[var(--z-hedgehog-buddy)] max-w-sm w-80 transition-all right-[calc(1rem-1px)]',
                isFloatingMaxExpanded && 'md:right-[calc(4rem-1px)]',
                !isFloatingMaxExpanded && 'md:right-[calc(3rem-1px)]'
            )}
        >
            <BindLogic logic={maxThreadLogic} props={threadProps}>
                <MaxFloatingInputContent />
            </BindLogic>
        </div>
    )
}
