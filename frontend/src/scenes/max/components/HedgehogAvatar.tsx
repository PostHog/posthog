import { IconSparkles } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { HedgehogActor, HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { useEffect, useRef } from 'react'
import { userLogic } from 'scenes/userLogic'

import { maxGlobalLogic } from '../maxGlobalLogic'
import { type PositionWithSide } from '../utils/floatingMaxPositioning'
import { useDragAndSnap } from '../utils/useDragAndSnap'

// Constants
const DEFAULT_WAVE_INTERVAL = 5000 // milliseconds

interface HedgehogAvatarProps {
    onExpand: () => void
    waveInterval?: number
    isExpanded: boolean
    fixedDirection?: 'left' | 'right'
    onPositionChange?: (position: PositionWithSide) => void
}

export function HedgehogAvatar({
    onExpand,
    waveInterval = DEFAULT_WAVE_INTERVAL,
    isExpanded,
    fixedDirection,
    onPositionChange,
}: HedgehogAvatarProps): JSX.Element {
    const { user } = useValues(userLogic)
    const hedgehogActorRef = useRef<HedgehogActor | null>(null)
    const avatarRef = useRef<HTMLDivElement>(null)
    const { setFloatingMaxDragState } = useActions(maxGlobalLogic)

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

    // Trigger wave animation periodically when collapsed
    useEffect(() => {
        let interval: ReturnType<typeof setInterval> | null = null

        if (!isExpanded && hedgehogActorRef.current) {
            interval = setInterval(() => {
                hedgehogActorRef.current?.setAnimation('wave')
            }, waveInterval)
        }

        return () => {
            if (interval) {
                clearInterval(interval)
            }
        }
    }, [isExpanded, waveInterval])

    return (
        <div
            ref={avatarRef}
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
                            Max AI - Create insights, talk to your data, and more
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
                                fixed_direction: fixedDirection,
                                ...user?.hedgehog_config,
                            }}
                            onActorLoaded={(actor) => {
                                hedgehogActorRef.current = actor
                                // Start with a wave
                                actor.setAnimation('wave')
                            }}
                        />
                    </div>
                </Tooltip>
            </div>
        </div>
    )
}
