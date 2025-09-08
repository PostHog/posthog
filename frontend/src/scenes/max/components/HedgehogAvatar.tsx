import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconSparkles } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { HedgehogModeProfile } from 'lib/components/HedgehogMode/HedgehogModeStatic'
import { hedgehogModeLogic } from 'lib/components/HedgehogMode/hedgehogModeLogic'

import { maxGlobalLogic } from '../maxGlobalLogic'
import { type PositionWithSide } from '../utils/floatingMaxPositioning'
import { useDragAndSnap } from '../utils/useDragAndSnap'

interface HedgehogAvatarProps {
    onExpand: () => void
    fixedDirection?: 'left' | 'right'
    onPositionChange?: (position: PositionWithSide) => void
}

export function HedgehogAvatar({ onExpand, fixedDirection, onPositionChange }: HedgehogAvatarProps): JSX.Element {
    const { setFloatingMaxDragState } = useActions(maxGlobalLogic)
    const { hedgehogConfig } = useValues(hedgehogModeLogic)

    // Use the drag and snap hook
    const { isDragging, isAnimating, hasDragged, containerStyle, handleMouseDown, dragElementRef } = useDragAndSnap({
        onPositionChange,
        disabled: false,
        currentSide: fixedDirection,
    })

    // Notify parent of drag state changes
    useEffect(() => {
        setFloatingMaxDragState({ isDragging, isAnimating })
    }, [isDragging, isAnimating, setFloatingMaxDragState])

    return (
        <div
            className={isDragging || isAnimating ? '' : 'relative flex items-center justify-end'}
            style={containerStyle}
            id="floating-max"
        >
            <div
                ref={dragElementRef}
                // border color should be the same as textarea :focus border
                className={`size-10 rounded-full overflow-hidden border border-[var(--border-bold)] transition-all duration-100 cursor-pointer -scale-x-100 hover:scale-y-110 hover:-scale-x-110 flex items-center justify-center bg-bg-light m-0.5 ${
                    isDragging ? 'cursor-grabbing' : 'cursor-grab'
                }`}
                onClick={() => {
                    if (!hasDragged && !isAnimating) {
                        onExpand()
                    }
                }}
                onMouseDown={handleMouseDown}
                style={{ pointerEvents: 'auto' }}
            >
                <Tooltip
                    title={
                        <>
                            <IconSparkles className="mr-1.5" />
                            Max is moving back into the sidebar
                        </>
                    }
                    placement="top-start"
                    delayMs={0}
                >
                    <div
                        style={{
                            width: '100%',
                            height: '100%',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                        }}
                    >
                        <HedgehogModeProfile config={hedgehogConfig} size="100%" direction="left" />
                    </div>
                </Tooltip>
            </div>
        </div>
    )
}
