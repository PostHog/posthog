import { useRef, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { LemonButton } from '@posthog/lemon-ui'
import { IconDrag } from '@posthog/icons'
import { maxGlobalLogic } from '../maxGlobalLogic'
import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { useDragAndSnap } from '../utils/useDragAndSnap'
import { FloatingSuggestionsDisplay } from './FloatingSuggestionsDisplay'
import { FloatingInputActions } from './FloatingInputActions'
import { ThreadAutoScroller } from './ThreadAutoScroller'
import { Thread } from '../Thread'
import { QuestionInput } from './QuestionInput'

interface ExpandedFloatingMaxProps {
    onCollapse: () => void
    onDismiss: () => void
}

export function ExpandedFloatingMax({ onCollapse, onDismiss }: ExpandedFloatingMaxProps): JSX.Element {
    const { dataProcessingAccepted, threadVisible } = useValues(maxLogic)
    const { isFloatingMaxExpanded, floatingMaxPosition, showFloatingMaxSuggestions } = useValues(maxGlobalLogic)
    const { setFloatingMaxPosition, setShowFloatingMaxSuggestions, setFloatingMaxDragState } =
        useActions(maxGlobalLogic)
    const { conversation } = useValues(maxThreadLogic)
    const expandedContainerRef = useRef<HTMLDivElement>(null)

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

    const handleCollapse = (): void => {
        setShowFloatingMaxSuggestions(false)
        onCollapse()
    }

    return (
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
                    onDismiss()
                }
            }}
        >
            <QuestionInput
                isFloating
                placeholder="Ask Max AI"
                contextDisplaySize="small"
                isThreadVisible={threadVisible}
                topActions={
                    !threadVisible ? (
                        <FloatingInputActions onCollapse={handleCollapse} isThreadVisible={false} />
                    ) : undefined
                }
                containerClassName="w-full max-w-[45rem] self-center"
                onSubmit={() => {
                    setShowFloatingMaxSuggestions(false)
                }}
                bottomActions={
                    <div className="px-1 -mt-1">
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
            >
                {showFloatingMaxSuggestions ? (
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
                ) : null}
            </QuestionInput>
        </div>
    )
}
