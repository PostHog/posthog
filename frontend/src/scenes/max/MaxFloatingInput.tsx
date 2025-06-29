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
import { calculateCSSPosition } from './utils/floatingMaxPositioning'

// Constants
const ANIMATION_DURATION = 200 // milliseconds

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
            containerClassName="w-full max-w-[45rem] self-center p-0"
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
    const { isFloatingMaxExpanded, floatingMaxPosition, floatingMaxDragState } = useValues(maxGlobalLogic)
    const { threadLogicKey, conversation, threadVisible } = useValues(maxLogic)
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const [floatingMaxPositionStyle, setFloatingMaxPositionStyle] = useState<React.CSSProperties | null>(null) // has to be useState as it's React.CSSProperties which doesn't work with kea

    const threadProps: MaxThreadLogicProps = {
        conversationId: threadLogicKey,
        conversation,
    }

    // Update position style when layout changes
    useEffect(() => {
        const side = floatingMaxPosition?.side || 'right'
        setFloatingMaxPositionStyle(calculateCSSPosition(side))
        // oxlint-disable-next-line exhaustive-deps
    }, [isFloatingMaxExpanded, isLayoutNavCollapsed, floatingMaxDragState, floatingMaxPosition])

    const getAnimationStyle = (): React.CSSProperties => {
        if (!isFloatingMaxExpanded) {
            return {}
        }

        const side = floatingMaxPosition?.side || 'right'
        const transformOrigin = side === 'left' ? 'bottom left' : 'bottom right'

        return {
            transformOrigin,
            animation: `MaxFloatingInput__ExpandFromAvatar ${ANIMATION_DURATION}ms cubic-bezier(0.4, 0, 0.2, 1)`,
        }
    }

    if (!featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG] || !featureFlags[FEATURE_FLAGS.FLOATING_ARTIFICIAL_HOG]) {
        return null
    }

    if (sidePanelOpen) {
        return null
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
                          isFloatingMaxExpanded ? 'rounded-lg w-80' : 'rounded-full',
                          !threadVisible && isFloatingMaxExpanded ? 'p-1' : 'p-0.5'
                      )
            }
            style={
                floatingMaxDragState.isDragging || floatingMaxDragState.isAnimating
                    ? {}
                    : { ...floatingMaxPositionStyle, ...getAnimationStyle() }
            }
        >
            <BindLogic logic={maxThreadLogic} props={threadProps}>
                <MaxFloatingInputContent />
            </BindLogic>
        </div>
    )
}
