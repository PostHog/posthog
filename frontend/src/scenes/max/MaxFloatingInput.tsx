import { IconSparkles, IconX } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { HedgehogActor, HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { timeSensitiveAuthenticationLogic } from 'lib/components/TimeSensitiveAuthentication/timeSensitiveAuthenticationLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useRef, useState } from 'react'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { userLogic } from 'scenes/userLogic'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { maxLogic } from './maxLogic'
import { maxThreadLogic, MaxThreadLogicProps } from './maxThreadLogic'
import { QuestionInput } from './QuestionInput'
import { generateBurstPoints } from './utils'

// Constants
const STORAGE_KEY = 'posthog-floating-max-expanded'
const WAVE_INTERVAL_MS = 5000

interface QuestionInputWithInteractionTrackingProps {
    isFloating?: boolean
    placeholder?: string
    onUserInteraction: () => void
}

function QuestionInputWithInteractionTracking({
    isFloating,
    placeholder,
    onUserInteraction,
}: QuestionInputWithInteractionTrackingProps): JSX.Element {
    const { question } = useValues(maxLogic)
    const { showAuthenticationModal } = useValues(timeSensitiveAuthenticationLogic)
    const previousQuestionRef = useRef(question)

    useEffect(() => {
        // Only track if user actually typed something new and no auth modal is open
        if (question !== previousQuestionRef.current && question.length > 0 && !showAuthenticationModal) {
            onUserInteraction()
        }
        previousQuestionRef.current = question
    }, [question, onUserInteraction, showAuthenticationModal])

    return <QuestionInput isFloating={isFloating} placeholder={placeholder} />
}

// Helper function to safely access localStorage
const getStoredExpansionState = (): boolean => {
    try {
        const saved = localStorage.getItem(STORAGE_KEY)
        return saved !== null ? JSON.parse(saved) : true
    } catch {
        return true // Default to expanded if localStorage is unavailable
    }
}

const setStoredExpansionState = (isExpanded: boolean): void => {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(isExpanded))
    } catch {
        // Silently fail if localStorage is unavailable (e.g., in private browsing)
    }
}

function MaxFloatingInputWithLogic(): JSX.Element {
    const { openSidePanel } = useActions(sidePanelLogic)
    const { activeStreamingThreads } = useValues(maxLogic)
    const { user } = useValues(userLogic)
    const { showAuthenticationModal } = useValues(timeSensitiveAuthenticationLogic)

    // Initialize state from localStorage, default to expanded (true)
    const [isExpanded, setIsExpanded] = useState(getStoredExpansionState)
    const [hasUserInteracted, setHasUserInteracted] = useState(false)
    const hedgehogActorRef = useRef<HedgehogActor | null>(null)

    // Memoized callbacks
    const handleExpand = (): void => {
        setHasUserInteracted(true)
        setIsExpanded(true)
    }

    const handleCollapse = (): void => {
        setIsExpanded(false)
    }

    const handleUserInteraction = (): void => {
        setHasUserInteracted(true)
    }

    const handleOpenSidePanel = (): void => {
        openSidePanel(SidePanelTab.Max)
    }

    // Persist expansion state to localStorage whenever it changes
    useEffect(() => {
        setStoredExpansionState(isExpanded)
    }, [isExpanded])

    // Watch for when a new conversation starts and open the sidebar
    useEffect(() => {
        if (activeStreamingThreads > 0) {
            openSidePanel(SidePanelTab.Max)
        }
    }, [activeStreamingThreads, openSidePanel])

    // Trigger wave animation periodically when collapsed
    useEffect(() => {
        if (!isExpanded && hedgehogActorRef.current) {
            const interval = setInterval(() => {
                hedgehogActorRef.current?.setAnimation('wave')
            }, WAVE_INTERVAL_MS)

            return () => clearInterval(interval)
        }
    }, [isExpanded])

    if (!isExpanded) {
        // Collapsed state - animated hedgehog in a circle
        return (
            <div className="relative flex items-center justify-end mb-2">
                <Tooltip
                    title={
                        <>
                            <IconSparkles className="mr-1.5" />
                            Ask Max
                        </>
                    }
                    placement="top-start"
                    delayMs={0}
                >
                    <div
                        className="size-10 rounded-full overflow-hidden border border-border-primary shadow-lg hover:shadow-xl transition-all duration-200 cursor-pointer -scale-x-100 hover:scale-y-110 hover:-scale-x-110 flex items-center justify-center bg-bg-light"
                        onClick={handleExpand}
                    >
                        <HedgehogBuddy
                            static
                            hedgehogConfig={{
                                controls_enabled: false,
                                walking_enabled: false,
                                color: null,
                                enabled: true,
                                accessories: [],
                                interactions_enabled: false,
                                party_mode_enabled: false,
                                use_as_profile: true,
                                skin: 'default',
                                ...user?.hedgehog_config,
                            }}
                            onActorLoaded={(actor) => {
                                hedgehogActorRef.current = actor
                                // Start with a wave
                                actor.setAnimation('wave')
                            }}
                            onClick={handleExpand}
                        />
                    </div>
                </Tooltip>
            </div>
        )
    }

    // Expanded state - show full input with hedgehog and close button
    const expandedContent = (
        <div className="relative">
            <QuestionInputWithInteractionTracking
                isFloating
                placeholder="Ask Max"
                onUserInteraction={handleUserInteraction}
            />

            {/* Close button */}
            <Tooltip title="Minimize" placement="top" delayMs={0}>
                <button
                    className="absolute -top-2 left-1 z-10 size-6 rounded-full bg-bg-light border border-border-primary hover:bg-bg-light-hover transition-colors duration-200 flex items-center justify-center"
                    type="button"
                    onClick={handleCollapse}
                >
                    <IconX className="size-3" />
                </button>
            </Tooltip>

            {/* Max hedgehog */}
            <Tooltip
                title={
                    <>
                        <IconSparkles className="mr-1.5" />
                        Ask Max
                    </>
                }
                placement="top-end"
                delayMs={0}
            >
                <button
                    className="absolute -top-2 right-6 z-10 transition duration-50 cursor-pointer -scale-x-100 hover:scale-y-110 hover:-scale-x-110"
                    type="button"
                    onClick={handleOpenSidePanel}
                >
                    {/* Burst border - the inset and size vals are very specific just bc these look nice */}
                    <svg className={clsx('absolute -inset-1 size-8')} viewBox="0 0 100 100">
                        <polygon points={generateBurstPoints(16, 3 / 16)} fill="var(--primary-3000)" />
                    </svg>
                    <ProfilePicture
                        user={{ hedgehog_config: { ...user?.hedgehog_config, use_as_profile: true } }}
                        size="md"
                        className="bg-bg-light"
                    />
                </button>
            </Tooltip>
        </div>
    )

    // Only show consent popover if user has interacted and no authentication modal is open
    if (hasUserInteracted && !showAuthenticationModal) {
        return (
            <AIConsentPopoverWrapper
                placement="top-start"
                fallbackPlacements={['top-end', 'bottom-start', 'bottom-end']}
                showArrow
                onDismiss={() => setHasUserInteracted(false)}
            >
                {expandedContent}
            </AIConsentPopoverWrapper>
        )
    }

    return expandedContent
}

export function MaxFloatingInput(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)

    const { threadLogicKey, conversation } = useValues(maxLogic)

    if (!featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG] || !featureFlags[FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG]) {
        return null
    }

    if (sidePanelOpen && selectedTab === SidePanelTab.Max) {
        return null
    }

    const threadProps: MaxThreadLogicProps = {
        conversationId: threadLogicKey,
        conversation,
    }

    return (
        <div className="fixed bottom-0 right-15 z-50 max-w-sm w-80">
            <BindLogic logic={maxThreadLogic} props={threadProps}>
                <MaxFloatingInputWithLogic />
            </BindLogic>
        </div>
    )
}
