import { BindLogic, useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useRef } from 'react'
import React from 'react'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'

import { QuestionInput } from './components/QuestionInput'
import { FloatingInputActions } from './components/FloatingInputActions'
import { HedgehogAvatar } from './components/HedgehogAvatar'
import { FloatingSuggestionsDisplay } from './components/FloatingSuggestionsDisplay'
import { ThreadAutoScroller } from './components/ThreadAutoScroller'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { maxThreadLogic, MaxThreadLogicProps } from './maxThreadLogic'
import { Thread } from './Thread'
import './MaxFloatingInput.scss'
import clsx from 'clsx'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { SidePanelTab } from '~/types'

interface MaxQuestionInputProps {
    placeholder?: string
    suggestions?: React.ReactNode
}

const MaxQuestionInput = React.forwardRef<HTMLDivElement, MaxQuestionInputProps>(function MaxQuestionInput(
    { placeholder, suggestions }: MaxQuestionInputProps,
    ref
) {
    const { focusCounter, threadVisible } = useValues(maxLogic)
    const { setIsFloatingMaxExpanded, setShowFloatingMaxSuggestions } = useActions(maxGlobalLogic)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)

    const handleCollapse = (): void => {
        setShowFloatingMaxSuggestions(false)
        setIsFloatingMaxExpanded(false)
    }

    useEffect(() => {
        if (textAreaRef.current) {
            textAreaRef.current.focus()
            textAreaRef.current.setSelectionRange(textAreaRef.current.value.length, textAreaRef.current.value.length)
        }
    }, [focusCounter])

    return (
        <QuestionInput
            ref={ref}
            isFloating
            placeholder={placeholder}
            contextDisplaySize="small"
            isThreadVisible={threadVisible}
            textAreaRef={textAreaRef}
            topActions={
                !threadVisible ? (
                    <FloatingInputActions onCollapse={handleCollapse} isThreadVisible={false} />
                ) : undefined
            }
            containerClassName="w-full max-w-[45rem] self-center"
            onSubmit={() => {
                setShowFloatingMaxSuggestions(false)
            }}
        >
            {suggestions}
        </QuestionInput>
    )
})

function MaxFloatingInputContent(): JSX.Element {
    const { dataProcessingAccepted, threadVisible } = useValues(maxLogic)
    const { setActiveGroup } = useActions(maxLogic)
    const { isFloatingMaxExpanded, floatingMaxPosition, showFloatingMaxSuggestions } = useValues(maxGlobalLogic)
    const { setIsFloatingMaxExpanded, setFloatingMaxPosition, setShowFloatingMaxSuggestions } =
        useActions(maxGlobalLogic)
    const { startNewConversation } = useActions(maxLogic)
    const { conversation } = useValues(maxThreadLogic)

    const handleExpand = (): void => {
        setIsFloatingMaxExpanded(true)
    }

    const handleDismiss = (): void => {
        setActiveGroup(null)
        setShowFloatingMaxSuggestions(false)
    }

    const handleCollapse = (): void => {
        setActiveGroup(null)
        setShowFloatingMaxSuggestions(false)
        setIsFloatingMaxExpanded(false)
        startNewConversation()
    }

    if (!isFloatingMaxExpanded) {
        return (
            <HedgehogAvatar
                onExpand={handleExpand}
                isExpanded={isFloatingMaxExpanded}
                onPositionChange={setFloatingMaxPosition}
                fixedDirection={floatingMaxPosition?.side === 'left' ? 'left' : 'right'}
            />
        )
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
                suggestions={
                    showFloatingMaxSuggestions ? (
                        <FloatingSuggestionsDisplay
                            compact
                            showSuggestions={showFloatingMaxSuggestions}
                            dataProcessingAccepted={dataProcessingAccepted}
                            type="tertiary"
                        />
                    ) : threadVisible ? (
                        <>
                            <div className="flex items-center justify-between pl-2 pr-1 py-1 border-b border-border">
                                <div className="text-xs font-medium text-muted">{conversation?.title}</div>
                                <div className="flex items-center gap-1">
                                    <FloatingInputActions onCollapse={handleCollapse} isThreadVisible={true} />
                                </div>
                            </div>
                            {/* Negative bottom margin so that the scrollable area touches the input */}
                            <div className="max-h-96 overflow-y-auto -mb-1">
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
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { scene, sceneConfig } = useValues(sceneLogic)
    const { isFloatingMaxExpanded, floatingMaxPosition, floatingMaxDragState } = useValues(maxGlobalLogic)
    const { threadLogicKey, conversation } = useValues(maxLogic)

    if (!featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG] || !featureFlags[FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG]) {
        return null
    }

    // Hide floating Max IF:
    if (
        (scene === Scene.Max && !isFloatingMaxExpanded) || // In the full Max scene, and Max is not intentionally in floating mode (i.e. expanded)
        (sidePanelOpen && selectedTab === SidePanelTab.Max) // The Max side panel is open
    ) {
        return null
    }

    if (sceneConfig?.layout === 'plain') {
        return null
    }

    const threadProps: MaxThreadLogicProps = {
        conversationId: threadLogicKey,
        conversation,
    }

    const getPositionClasses = (): string => {
        const side = floatingMaxPosition?.side || 'right'
        const baseClasses = 'fixed bottom-0 z-[var(--z-hedgehog-buddy)] max-w-sm'

        if (!isFloatingMaxExpanded) {
            // When collapsed, avatar position matches the side
            if (side === 'left') {
                return `${baseClasses} left-[calc(1rem-1px)] md:left-[calc(17rem-1px)]`
            }
            return `${baseClasses} right-[calc(1rem-1px)] md:right-[calc(3rem-1px)]`
        }

        // When expanded, panel stays on same side but moves away from avatar
        // If avatar is on right, panel moves further left on right side
        // If avatar is on left, panel moves further right on left side
        if (side === 'left') {
            return `${baseClasses} left-[calc(1rem-1px)] md:left-[calc(17rem-1px)]`
        }
        return `${baseClasses} right-[calc(1rem-1px)] md:right-[calc(4rem-1px)]`
    }

    const getAnimationStyle = (): React.CSSProperties => {
        const side = floatingMaxPosition?.side || 'right'

        if (!isFloatingMaxExpanded) {
            return {}
        }

        // Transform origin should be where the avatar is relative to the panel
        if (side === 'left') {
            // Avatar is to the left of panel, so origin is bottom-left
            return {
                transformOrigin: 'bottom left',
                animation: 'MaxFloatingInput__ExpandFromAvatar 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
            }
        }
        // Avatar is to the right of panel, so origin is bottom-right
        return {
            transformOrigin: 'bottom right',
            animation: 'MaxFloatingInput__ExpandFromAvatar 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
        }
    }

    return (
        <div
            className={
                floatingMaxDragState.isDragging || floatingMaxDragState.isAnimating
                    ? ''
                    : clsx(
                          getPositionClasses(),
                          'border backdrop-blur-sm bg-[var(--glass-bg-3000)] mb-2',
                          isFloatingMaxExpanded ? 'rounded-lg w-80' : 'rounded-full mr-4'
                      )
            }
            style={floatingMaxDragState.isDragging || floatingMaxDragState.isAnimating ? {} : getAnimationStyle()}
        >
            <BindLogic logic={maxThreadLogic} props={threadProps}>
                <MaxFloatingInputContent />
            </BindLogic>
        </div>
    )
}
