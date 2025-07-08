import { BindLogic, useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React, { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

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
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { SidePanelTab } from '~/types'
import { calculateCSSPosition } from './utils/floatingMaxPositioning'
import { useDragAndSnap } from './utils/useDragAndSnap'
import { LemonButton } from '@posthog/lemon-ui'
import { IconDrag } from '@posthog/icons'

interface MaxQuestionInputProps {
    placeholder?: string
    suggestions?: React.ReactNode
    bottomActions?: React.ReactNode
}

const MaxQuestionInput = React.forwardRef<HTMLDivElement, MaxQuestionInputProps>(function MaxQuestionInput(
    { placeholder, suggestions, bottomActions }: MaxQuestionInputProps,
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
            bottomActions={bottomActions}
        >
            {suggestions}
        </QuestionInput>
    )
})

function MaxFloatingInputContent(): JSX.Element {
    const { dataProcessingAccepted, threadVisible } = useValues(maxLogic)
    const { setActiveGroup } = useActions(maxLogic)
    const { isFloatingMaxExpanded, floatingMaxPosition, showFloatingMaxSuggestions, floatingMaxDragState } =
        useValues(maxGlobalLogic)
    const { setIsFloatingMaxExpanded, setFloatingMaxPosition, setShowFloatingMaxSuggestions, setFloatingMaxDragState } =
        useActions(maxGlobalLogic)
    const { startNewConversation } = useActions(maxLogic)
    const { conversation } = useValues(maxThreadLogic)
    const expandedContainerRef = useRef<HTMLDivElement>(null)
    const [shouldAnimate, setShouldAnimate] = useState(false)
    const prevExpandedRef = useRef(isFloatingMaxExpanded)
    const [floatingMaxPositionStyle, setFloatingMaxPositionStyle] = useState<React.CSSProperties>({}) // has to be useState as it's React.CSSProperties which doesn't work with kea
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)

    // Use drag and snap for expanded floating input
    const { isDragging, isAnimating, containerStyle, handleMouseDown, dragElementRef } = useDragAndSnap({
        onPositionChange: setFloatingMaxPosition,
        disabled: !isFloatingMaxExpanded,
        currentSide: floatingMaxPosition?.side,
        containerRef: expandedContainerRef,
    })

    // Notify parent of drag state changes for expanded input
    useEffect(() => {
        if (isFloatingMaxExpanded) {
            setFloatingMaxDragState({ isDragging, isAnimating })
        }
    }, [isDragging, isAnimating, isFloatingMaxExpanded, setFloatingMaxDragState])

    // Only animate when transitioning from collapsed to expanded
    useEffect(() => {
        const wasCollapsed = !prevExpandedRef.current
        const isNowExpanded = isFloatingMaxExpanded

        if (wasCollapsed && isNowExpanded) {
            setShouldAnimate(true)
            // Clear animation flag after animation completes
            const timer = setTimeout(() => setShouldAnimate(false), 200)
            return () => clearTimeout(timer)
        }

        prevExpandedRef.current = isFloatingMaxExpanded
    }, [isFloatingMaxExpanded])

    // Update position style when layout changes
    useEffect(() => {
        const side = floatingMaxPosition?.side || 'right'
        const baseStyle = isFloatingMaxExpanded
            ? {
                  borderRadius: '8px',
                  transformOrigin: floatingMaxPosition?.side === 'left' ? 'bottom left' : 'bottom right',
                  ...(shouldAnimate
                      ? { animation: 'MaxFloatingInput__ExpandFromAvatar 0.2s cubic-bezier(0.4, 0, 0.2, 1)' }
                      : {}),
              }
            : {
                  borderRadius: '50%',
              }

        setFloatingMaxPositionStyle({
            ...calculateCSSPosition(side),
            ...baseStyle,
        })
        // oxlint-disable-next-line exhaustive-deps
    }, [isFloatingMaxExpanded, isLayoutNavCollapsed, floatingMaxDragState, floatingMaxPosition, shouldAnimate])

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
            data-attr="floating-max-container"
            className={
                floatingMaxDragState.isDragging || floatingMaxDragState.isAnimating
                    ? ''
                    : clsx(
                          'fixed bottom-0 z-[var(--z-hedgehog-buddy)] max-w-sm',
                          'border backdrop-blur-sm bg-[var(--glass-bg-3000)] mb-2',
                          isFloatingMaxExpanded ? 'rounded-lg w-80' : 'rounded-full'
                      )
            }
            style={
                floatingMaxDragState.isDragging || floatingMaxDragState.isAnimating
                    ? {
                          position: 'fixed',
                          zIndex: 1000,
                          maxWidth: '20rem',
                          border: '1px solid var(--border)',
                          backdropFilter: 'blur(4px)',
                          backgroundColor: 'var(--glass-bg-3000)',
                          marginBottom: '0.5rem',
                          borderRadius: isFloatingMaxExpanded ? '8px' : '50%',
                          width: isFloatingMaxExpanded ? '20rem' : undefined,
                          marginRight: isFloatingMaxExpanded ? undefined : '1rem',
                      }
                    : floatingMaxPositionStyle
            }
        >
            <div
                ref={expandedContainerRef}
                className={
                    isDragging || isAnimating
                        ? 'flex flex-col rounded-lg w-80 border backdrop-blur-sm bg-[var(--glass-bg-3000)] mb-2'
                        : 'relative flex flex-col'
                }
                style={isDragging || isAnimating ? containerStyle : {}}
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
                    bottomActions={
                        <div className="px-1 -mt-0.5">
                            <div
                                ref={dragElementRef}
                                className={`flex items-center justify-center cursor-grab ${
                                    isDragging ? 'cursor-grabbing' : 'cursor-grab'
                                }`}
                                onMouseDown={handleMouseDown}
                                style={{ pointerEvents: 'auto' }}
                            >
                                <LemonButton
                                    size="xxsmall"
                                    icon={<IconDrag className="size-3" />}
                                    type="tertiary"
                                    tooltip="Drag to move"
                                />
                            </div>
                        </div>
                    }
                />
            </div>
        </div>
    )
}

export function MaxFloatingInput(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { scene, sceneConfig } = useValues(sceneLogic)
    const { isFloatingMaxExpanded } = useValues(maxGlobalLogic)
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

    return (
        <BindLogic logic={maxThreadLogic} props={threadProps}>
            <MaxFloatingInputContent />
        </BindLogic>
    )
}
