import { BindLogic, useActions, useValues } from 'kea'
import { timeSensitiveAuthenticationLogic } from 'lib/components/TimeSensitiveAuthentication/timeSensitiveAuthenticationLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useRef } from 'react'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { BaseQuestionInput } from './components/BaseQuestionInput'
import { FloatingInputActions } from './components/FloatingInputActions'
import { HedgehogAvatar } from './components/HedgehogAvatar'
import { SuggestionsDisplay } from './components/SuggestionsDisplay'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { maxThreadLogic, MaxThreadLogicProps } from './maxThreadLogic'

interface QuestionInputWithInteractionTrackingProps {
    placeholder?: string
    onUserInteraction: () => void
    suggestions?: React.ReactNode
}

function QuestionInputWithInteractionTracking({
    placeholder,
    onUserInteraction,
    suggestions,
}: QuestionInputWithInteractionTrackingProps): JSX.Element {
    const { question } = useValues(maxLogic)
    const { showAuthenticationModal } = useValues(timeSensitiveAuthenticationLogic)
    const previousQuestionRef = useRef(question)
    const { showSuggestions } = useValues(maxLogic)
    const { setShowSuggestions } = useActions(maxLogic)
    const { setIsFloatingMaxExpanded } = useActions(maxGlobalLogic)

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

    return (
        <BaseQuestionInput
            isFloating={true}
            placeholder={placeholder}
            contextDisplaySize="small"
            showTopActions
            topActions={<FloatingInputActions showSuggestions={showSuggestions} onCollapse={handleCollapse} />}
            containerClassName="px-1 sticky bottom-0 z-10 w-full max-w-[45rem] self-center"
        >
            {suggestions}
        </BaseQuestionInput>
    )
}

function MaxFloatingInputWithLogic(): JSX.Element {
    const { showAuthenticationModal } = useValues(timeSensitiveAuthenticationLogic)
    const { openSidePanel } = useActions(sidePanelLogic)
    const { activeStreamingThreads, dataProcessingAccepted, showSuggestions } = useValues(maxLogic)
    const { setShowSuggestions, setActiveGroup } = useActions(maxLogic)
    const { isFloatingMaxExpanded, userHasInteractedWithFloatingMax } = useValues(maxGlobalLogic)
    const { setIsFloatingMaxExpanded, setUserHasInteractedWithFloatingMax } = useActions(maxGlobalLogic)

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

    // Watch for when a new conversation starts and open the sidebar
    useEffect(() => {
        if (activeStreamingThreads > 0) {
            openSidePanel(SidePanelTab.Max)
        }
    }, [activeStreamingThreads, openSidePanel])

    if (!isFloatingMaxExpanded) {
        return <HedgehogAvatar onExpand={handleExpand} isExpanded={isFloatingMaxExpanded} />
    }

    // Expanded state - show full input with suggestions when focused
    const expandedContent = (
        <div
            className="relative"
            onBlur={(e) => {
                // Only lose focus if clicking outside the entire container
                if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                    handleDismiss()
                }
            }}
        >
            <QuestionInputWithInteractionTracking
                placeholder="Ask Max AI"
                onUserInteraction={handleUserInteraction}
                suggestions={
                    <SuggestionsDisplay
                        compact
                        showSuggestions={showSuggestions}
                        dataProcessingAccepted={dataProcessingAccepted}
                        type="tertiary"
                    />
                }
            />
        </div>
    )

    // Only show consent popover if user has interacted and no authentication modal is open
    if (userHasInteractedWithFloatingMax && !showAuthenticationModal) {
        return (
            <AIConsentPopoverWrapper
                placement="top-start"
                fallbackPlacements={['top-end', 'bottom-start', 'bottom-end']}
                showArrow
                onDismiss={() => setUserHasInteractedWithFloatingMax(false)}
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
        <div className="fixed bottom-0 z-[var(--z-popover)] max-w-sm w-80 transition-all md:right-[calc(3rem-1px)] right-[calc(1rem-1px)]">
            <BindLogic logic={maxThreadLogic} props={threadProps}>
                <MaxFloatingInputWithLogic />
            </BindLogic>
        </div>
    )
}
