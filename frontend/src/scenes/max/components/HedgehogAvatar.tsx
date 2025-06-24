import { IconSparkles } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { HedgehogActor, HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { useEffect, useRef } from 'react'
import { userLogic } from 'scenes/userLogic'

import { useDragAndSnap } from '../hooks/useDragAndSnap'

interface HedgehogAvatarProps {
    onExpand: () => void
    waveInterval?: number
    isExpanded: boolean
    fixedDirection?: 'left' | 'right'
    onPositionChange?: (position: { x: number; y: number; side: 'left' | 'right' }) => void
    onDragStateChange?: (isDragging: boolean, isAnimating: boolean) => void
}

export function HedgehogAvatar({
    onExpand,
    waveInterval = 5000,
    isExpanded,
    fixedDirection,
    onPositionChange,
    onDragStateChange,
}: HedgehogAvatarProps): JSX.Element {
    const { user } = useValues(userLogic)
    const hedgehogActorRef = useRef<HedgehogActor | null>(null)
    const avatarRef = useRef<HTMLDivElement>(null)

    // Use the drag and snap hook
    const { isDragging, isAnimating, hasDragged, containerStyle, handleMouseDown, avatarButtonRef } = useDragAndSnap({
        onPositionChange,
        disabled: false,
    })

    // Notify parent of drag state changes
    useEffect(() => {
        if (onDragStateChange) {
            onDragStateChange(isDragging, isAnimating)
        }
    }, [isDragging, isAnimating, onDragStateChange])

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
                    ref={avatarButtonRef}
                    className={`size-10 rounded-full overflow-hidden border border-border-primary shadow-lg hover:shadow-xl transition-all duration-200 cursor-pointer -scale-x-100 hover:scale-y-110 hover:-scale-x-110 flex items-center justify-center bg-bg-light ${
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
    )
}
