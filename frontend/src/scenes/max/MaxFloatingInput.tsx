import {
    IconArrowRight,
    IconChevronDown,
    IconChevronLeft,
    IconClockRewind,
    IconEllipsis,
    IconLightBulb,
    IconSidePanel,
    IconSparkles,
    IconStopFilled,
    IconX,
} from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems, LemonTextArea, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { HedgehogActor, HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { timeSensitiveAuthenticationLogic } from 'lib/components/TimeSensitiveAuthentication/timeSensitiveAuthenticationLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconTools } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useRef } from 'react'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { userLogic } from 'scenes/userLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { ContextDisplay } from './ContextDisplay'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic, QUESTION_SUGGESTIONS_DATA } from './maxLogic'
import { maxThreadLogic, MaxThreadLogicProps } from './maxThreadLogic'
import { checkSuggestionRequiresUserInput, stripSuggestionPlaceholders } from './utils'

// Constants
const WAVE_INTERVAL_MS = 5000

interface QuestionInputWithInteractionTrackingProps {
    isFloating?: boolean
    placeholder?: string
    onUserInteraction: () => void
    suggestions?: React.ReactNode
}

function QuestionInputWithInteractionTracking({
    isFloating,
    placeholder,
    onUserInteraction,
    suggestions,
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

    return <QuestionInputWithSuggestions isFloating={isFloating} placeholder={placeholder} suggestions={suggestions} />
}

interface QuestionInputWithSuggestionsProps {
    isFloating?: boolean
    placeholder?: string
    suggestions?: React.ReactNode
}

function QuestionInputWithSuggestions({
    isFloating,
    placeholder,
    suggestions,
}: QuestionInputWithSuggestionsProps): JSX.Element {
    const { tools } = useValues(maxGlobalLogic)

    const { question, showSuggestions } = useValues(maxLogic)
    const { setQuestion, setShowSuggestions, toggleConversationHistory, setActiveGroup } = useActions(maxLogic)
    const { openSidePanel } = useActions(sidePanelLogic)

    const { threadLoading, inputDisabled, submissionDisabledReason } = useValues(maxThreadLogic)
    const { askMax, stopGeneration } = useActions(maxThreadLogic)
    const { setIsFloatingMaxExpanded } = useActions(maxGlobalLogic)

    const handleCollapse = (): void => {
        setShowSuggestions(false)
        setIsFloatingMaxExpanded(false)
    }

    return (
        <div
            className={clsx(
                'px-1',
                !isFloating ? 'w-[min(44rem,100%)]' : 'sticky bottom-0 z-10 w-full max-w-[45rem] self-center'
            )}
        >
            <div
                className={clsx(
                    'flex flex-col items-center',
                    isFloating &&
                        'p-1 mb-2 border border-[var(--border-primary)] rounded-lg backdrop-blur-sm bg-[var(--glass-bg-3000)]'
                )}
            >
                <div className="relative w-full">
                    {/* Suggestions at the top, inside the border */}
                    {suggestions}
                    <div
                        className={clsx(
                            'flex flex-col',
                            'border border-[var(--border-primary)] rounded-[var(--radius)]',
                            'bg-[var(--bg-fill-input)]',
                            'hover:border-[var(--border-bold)] focus-within:border-[var(--border-bold)]',
                            isFloating && 'border-primary'
                        )}
                    >
                        <div className="flex items-start justify-between">
                            <ContextDisplay size="small" />
                            <div className="flex items-start gap-1 h-full mt-1 mr-1">
                                <Tooltip
                                    title={showSuggestions ? 'Hide suggestions' : 'Show suggestions'}
                                    placement="top"
                                    delayMs={0}
                                >
                                    <LemonButton
                                        size="xxsmall"
                                        icon={
                                            showSuggestions ? (
                                                <IconChevronDown className="size-3" />
                                            ) : (
                                                <IconLightBulb className="size-3" />
                                            )
                                        }
                                        type="tertiary"
                                        onClick={() => {
                                            setShowSuggestions(!showSuggestions)
                                            setActiveGroup(null)
                                        }}
                                    />
                                </Tooltip>
                                <LemonMenu
                                    items={
                                        [
                                            {
                                                label: 'Open in sidebar',
                                                icon: <IconSidePanel />,
                                                onClick: () => openSidePanel(SidePanelTab.Max),
                                                size: 'xsmall',
                                            },
                                            {
                                                label: 'Open conversation history',
                                                icon: <IconClockRewind />,
                                                onClick: () => {
                                                    toggleConversationHistory()
                                                    openSidePanel(SidePanelTab.Max)
                                                },
                                                size: 'xsmall',
                                            },
                                        ] as LemonMenuItems
                                    }
                                    placement="bottom-end"
                                >
                                    <LemonButton
                                        size="xxsmall"
                                        icon={<IconEllipsis className="size-3" />}
                                        type="tertiary"
                                    />
                                </LemonMenu>

                                <Tooltip title="Minimize" placement="top" delayMs={0}>
                                    <LemonButton
                                        size="xxsmall"
                                        icon={<IconX className="size-3" />}
                                        type="tertiary"
                                        onClick={handleCollapse}
                                    />
                                </Tooltip>
                            </div>
                        </div>
                        <LemonTextArea
                            value={question}
                            onChange={(value) => setQuestion(value)}
                            placeholder={
                                threadLoading ? 'Thinking…' : isFloating ? placeholder || 'Ask follow-up' : 'Ask away'
                            }
                            onPressEnter={() => {
                                if (question && !submissionDisabledReason && !threadLoading) {
                                    askMax(question)
                                }
                            }}
                            disabled={inputDisabled}
                            minRows={1}
                            maxRows={10}
                            className={clsx(
                                '!border-none !bg-transparent min-h-0 py-2.5 pl-2.5',
                                isFloating ? 'pr-20' : 'pr-12'
                            )}
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

function MaxFloatingInputWithLogic(): JSX.Element {
    const { openSidePanel } = useActions(sidePanelLogic)
    const { activeStreamingThreads, dataProcessingAccepted, activeSuggestionGroup, showSuggestions } =
        useValues(maxLogic)
    const { setQuestion, focusInput, setActiveGroup, setShowSuggestions } = useActions(maxLogic)
    const { askMax } = useActions(maxThreadLogic)
    const { isFloatingMaxExpanded, userHasInteractedWithFloatingMax } = useValues(maxGlobalLogic)
    const { setIsFloatingMaxExpanded, setUserHasInteractedWithFloatingMax } = useActions(maxGlobalLogic)
    const { user } = useValues(userLogic)
    const { showAuthenticationModal } = useValues(timeSensitiveAuthenticationLogic)
    const hedgehogActorRef = useRef<HedgehogActor | null>(null)

    const handleExpand = (): void => {
        setUserHasInteractedWithFloatingMax(true)
        setIsFloatingMaxExpanded(true)
    }

    const handleUserInteraction = (): void => {
        setUserHasInteractedWithFloatingMax(true)
    }

    // Watch for when a new conversation starts and open the sidebar
    useEffect(() => {
        if (activeStreamingThreads > 0) {
            openSidePanel(SidePanelTab.Max)
        }
    }, [activeStreamingThreads, openSidePanel])

    // Trigger wave animation periodically when collapsed
    useEffect(() => {
        let interval: ReturnType<typeof setInterval> | null = null

        if (!isFloatingMaxExpanded && hedgehogActorRef.current) {
            interval = setInterval(() => {
                hedgehogActorRef.current?.setAnimation('wave')
            }, WAVE_INTERVAL_MS)
        }

        return () => {
            if (interval) {
                clearInterval(interval)
            }
        }
    }, [isFloatingMaxExpanded])

    if (!isFloatingMaxExpanded) {
        // Collapsed state - animated hedgehog in a circle
        return (
            <div className="relative flex items-center justify-end mb-2 mr-4">
                <Tooltip
                    title={
                        <>
                            <IconSparkles className="mr-1.5" />
                            Max AI - Create insights, talk to your data, and more
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

    // Expanded state - show full input with suggestions when focused
    const expandedContent = (
        <div
            className="relative"
            onBlur={(e) => {
                // Only lose focus if clicking outside the entire container
                if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                    setActiveGroup(null)
                    setShowSuggestions(false)
                }
            }}
        >
            <div className="relative">
                <QuestionInputWithInteractionTracking
                    isFloating
                    placeholder="Ask Max AI"
                    onUserInteraction={handleUserInteraction}
                    suggestions={
                        <>
                            {/* Suggestions - show only when button is clicked and empty */}
                            {showSuggestions && !activeSuggestionGroup && (
                                <div className="px-0.5 pt-1 pb-1">
                                    <div className="flex flex-wrap gap-1">
                                        {QUESTION_SUGGESTIONS_DATA.map((group) => (
                                            <LemonButton
                                                key={group.label}
                                                onClick={() => {
                                                    // If it's a product-based skill, open the URL first
                                                    if (
                                                        group.url &&
                                                        !router.values.currentLocation.pathname.includes(group.url)
                                                    ) {
                                                        router.actions.push(group.url)
                                                    }

                                                    // If there's only one suggestion, we can just ask Max directly
                                                    if (group.suggestions.length <= 1) {
                                                        if (
                                                            checkSuggestionRequiresUserInput(
                                                                group.suggestions[0].content
                                                            )
                                                        ) {
                                                            setQuestion(
                                                                stripSuggestionPlaceholders(
                                                                    group.suggestions[0].content
                                                                )
                                                            )
                                                            focusInput()
                                                        } else {
                                                            askMax(group.suggestions[0].content)
                                                        }
                                                    } else {
                                                        setActiveGroup(group)
                                                    }
                                                }}
                                                size="xxsmall"
                                                type="tertiary"
                                                icon={group.icon}
                                                center
                                                disabledReason={
                                                    !dataProcessingAccepted
                                                        ? 'Please accept OpenAI processing data'
                                                        : undefined
                                                }
                                                tooltip={group.tooltip}
                                            >
                                                {group.label}
                                            </LemonButton>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Detailed suggestions when a group is active */}
                            {showSuggestions && activeSuggestionGroup && (
                                <div className="px-0.5 pt-1 pb-1">
                                    <div className="flex items-center gap-1 mb-1">
                                        <LemonButton
                                            size="xxsmall"
                                            type="tertiary"
                                            icon={<IconChevronLeft />}
                                            onClick={() => setActiveGroup(null)}
                                            tooltip="Back to categories"
                                        />
                                        <div className="flex items-center gap-1">
                                            {activeSuggestionGroup.icon}
                                            <span className="text-xxs font-medium">{activeSuggestionGroup.label}</span>
                                        </div>
                                    </div>
                                    <div className="flex flex-col gap-1">
                                        {activeSuggestionGroup.suggestions.map((suggestion, index) => (
                                            <LemonButton
                                                key={index}
                                                onClick={() => {
                                                    if (checkSuggestionRequiresUserInput(suggestion.content)) {
                                                        setQuestion(stripSuggestionPlaceholders(suggestion.content))
                                                        focusInput()
                                                    } else {
                                                        askMax(suggestion.content)
                                                    }
                                                    setActiveGroup(null)
                                                }}
                                                size="xxsmall"
                                                type="tertiary"
                                                fullWidth
                                                disabledReason={
                                                    !dataProcessingAccepted
                                                        ? 'Please accept OpenAI processing data'
                                                        : undefined
                                                }
                                            >
                                                {suggestion.content.replace(/\{[^}]*\}/g, '...')}
                                            </LemonButton>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </>
                    }
                />
            </div>
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
        <div
            className={clsx('fixed bottom-0 z-[var(--z-popover)] max-w-sm w-80 transition-all', {
                'right-[calc(1rem-1px)]': sidePanelOpen,
                'right-[calc(3rem-1px)]': !sidePanelOpen,
            })}
        >
            <BindLogic logic={maxThreadLogic} props={threadProps}>
                <MaxFloatingInputWithLogic />
            </BindLogic>
        </div>
    )
}
