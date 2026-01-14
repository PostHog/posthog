import clsx from 'clsx'

import { SnapPosition } from 'lib/hooks/useDraggableSnap'

const DEFAULT_HITBOX_SIZE = 100

interface DraggableSnapZonesProps {
    /** Whether the element is currently being dragged */
    isDragging: boolean
    /** The snap zone positions from useDraggableSnap */
    snapZones: Record<SnapPosition, { x: number; y: number }>
    /** Currently snapped position, or null if freely positioned */
    fixedPosition: SnapPosition | null
    /** Size of the snap hitbox in pixels. Defaults to 100. */
    hitboxSize?: number
}

export function DraggableSnapZones({
    isDragging,
    snapZones,
    fixedPosition,
    hitboxSize = DEFAULT_HITBOX_SIZE,
}: DraggableSnapZonesProps): JSX.Element | null {
    if (!isDragging) {
        return null
    }

    return (
        <div className="w-full h-full fixed inset-0 pointer-events-none overflow-hidden z-[var(--z-modal)]">
            {Object.entries(snapZones).map(([key, { x, y }]) => (
                <DraggableSnapZone
                    key={key}
                    position={{ x, y }}
                    isSelected={key === fixedPosition}
                    hitboxSize={hitboxSize}
                />
            ))}
        </div>
    )
}

interface DraggableSnapZoneProps {
    position: { x: number; y: number }
    isSelected: boolean
    hitboxSize: number
}

function DraggableSnapZone({ position, isSelected, hitboxSize }: DraggableSnapZoneProps): JSX.Element {
    return (
        <div
            className={clsx(
                'transition-all absolute border rounded-lg',
                isSelected ? 'bg-primary opacity-50' : 'bg-primary opacity-20'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: position.x,
                top: position.y,
                marginLeft: -hitboxSize * 0.5,
                marginTop: -hitboxSize * 0.5,
                width: hitboxSize,
                height: hitboxSize,
                transform: isSelected ? 'scale(1.25)' : 'scale(1)',
            }}
        />
    )
}
