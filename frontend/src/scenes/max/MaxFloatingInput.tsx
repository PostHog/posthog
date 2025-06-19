import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { timeSensitiveAuthenticationLogic } from 'lib/components/TimeSensitiveAuthentication/timeSensitiveAuthenticationLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useRef, useState } from 'react'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

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

interface UseConsentPopoverReturn {
    showConsentPopover: boolean
    setShowConsentPopover: (show: boolean) => void
}

export function useConsentPopover(
    userHasInteracted: boolean,
    showAuthModal: boolean,
    questionLength: number
): UseConsentPopoverReturn {
    const [showConsentPopover, setShowConsentPopover] = useState(false)
    const consentDelayTimeoutRef = useRef<NodeJS.Timeout | null>(null)

    useEffect(() => {
        if (userHasInteracted && !showAuthModal) {
            if (consentDelayTimeoutRef.current) {
                clearTimeout(consentDelayTimeoutRef.current)
            }

            if (questionLength > 0) {
                consentDelayTimeoutRef.current = setTimeout(() => {
                    setShowConsentPopover(true)
                }, 1000)
            } else {
                setShowConsentPopover(true)
            }
        } else {
            setShowConsentPopover(false)
        }

        return () => {
            if (consentDelayTimeoutRef.current) {
                clearTimeout(consentDelayTimeoutRef.current)
            }
        }
    }, [userHasInteracted, showAuthModal, questionLength])

    return {
        showConsentPopover,
        setShowConsentPopover,
    }
}

interface MaxQuestionInputProps {
    placeholder?: string
    onUserInteraction: () => void
    suggestions?: React.ReactNode
    hideTopActions?: boolean
}

function MaxQuestionInput({
    placeholder,
    onUserInteraction,
    suggestions,
    hideTopActions = false,
}: MaxQuestionInputProps): JSX.Element {
    const { question, focusCounter } = useValues(maxLogic)
    const { showAuthenticationModal } = useValues(timeSensitiveAuthenticationLogic)
    const previousQuestionRef = useRef(question)
    const { showSuggestions } = useValues(maxLogic)
    const { setShowSuggestions } = useActions(maxLogic)
    const { setIsFloatingMaxExpanded } = useActions(maxGlobalLogic)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)

    const handleCollapse = (): void => {
        setShowSuggestions(false)
        setIsFloatingMaxExpanded(false)
    }

    useEffect(() => {
        // Only track if user actually typed something new and no auth modal is open
        if (question !== previousQuestionRef.current && question.length > 0 && !showAuthenticationModal) {
            onUserInteraction()
        }
        previousQuestionRef.current = question
    }, [question, onUserInteraction, showAuthenticationModal])

    useEffect(() => {
        if (textAreaRef.current) {
            textAreaRef.current.focus()
            textAreaRef.current.setSelectionRange(textAreaRef.current.value.length, textAreaRef.current.value.length)
        }
    }, [focusCounter])

    return (
        <BaseQuestionInput
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
}

function MaxFloatingInputContent(): JSX.Element {
    const { showAuthenticationModal } = useValues(timeSensitiveAuthenticationLogic)
    const { dataProcessingAccepted, showSuggestions, threadVisible, question } = useValues(maxLogic)
    const { setShowSuggestions, setActiveGroup } = useActions(maxLogic)
    const { isFloatingMaxExpanded, userHasInteractedWithFloatingMax } = useValues(maxGlobalLogic)
    const { setIsFloatingMaxExpanded, setUserHasInteractedWithFloatingMax } = useActions(maxGlobalLogic)
    const { startNewConversation } = useActions(maxLogic)
    const { conversation } = useValues(maxThreadLogic)

    const { showConsentPopover, setShowConsentPopover } = useConsentPopover(
        userHasInteractedWithFloatingMax,
        showAuthenticationModal,
        question.length
    )

    const handleExpand = (): void => {
        setUserHasInteractedWithFloatingMax(true)
        setIsFloatingMaxExpanded(true)
    }

    const handleUserInteraction = (): void => {
        setUserHasInteractedWithFloatingMax(true)
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

    // Removed automatic sidebar opening - conversations now show in floating view

    if (!isFloatingMaxExpanded) {
        return <HedgehogAvatar onExpand={handleExpand} isExpanded={isFloatingMaxExpanded} />
    }

    // Expanded state - show thread and input
    const expandedContent = (
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
                onUserInteraction={handleUserInteraction}
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

    if (showConsentPopover) {
        return (
            <AIConsentPopoverWrapper
                placement="top-start"
                fallbackPlacements={['top-end', 'bottom-start', 'bottom-end']}
                showArrow
                onDismiss={() => {
                    setUserHasInteractedWithFloatingMax(false)
                    setShowConsentPopover(false)
                }}
            >
                {expandedContent}
            </AIConsentPopoverWrapper>
        )
    }

    return expandedContent
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
                'fixed bottom-0 z-[var(--z-popover)] max-w-sm w-80 transition-all right-[calc(1rem-1px)]',
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
