import clsx from 'clsx'
import { useValues } from 'kea'

import { TOOLBAR_FIXED_POSITION_HITBOX, toolbarLogic } from './toolbarLogic'

export function ToolbarFixedZones(): JSX.Element | null {
    const { isDragging, fixedPositions } = useValues(toolbarLogic)

    if (!isDragging) {
        return null
    }

    return (
        <div className="w-full h-full absolute top-0 left-0 pointer-events-none overflow-hidden">
            {Object.entries(fixedPositions).map(([key, { x, y }]) => (
                <ToolbarFixedZone key={key} id={key} position={{ x, y }} />
            ))}
        </div>
    )
}

function ToolbarFixedZone({ id, position }: { id: string; position: { x: number; y: number } }): JSX.Element {
    const { fixedPosition, lastDragPosition } = useValues(toolbarLogic)

    const selected = id === fixedPosition && !lastDragPosition

    return (
        <div
            className={clsx(
                'transition-all absolute border rounded-lg bg-primary',
                selected ? 'opacity-50' : 'opacity-20'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: position.x,
                top: position.y,
                marginLeft: -TOOLBAR_FIXED_POSITION_HITBOX * 0.5,
                marginTop: -TOOLBAR_FIXED_POSITION_HITBOX * 0.5,
                width: TOOLBAR_FIXED_POSITION_HITBOX,
                height: TOOLBAR_FIXED_POSITION_HITBOX,
                transform: selected ? 'scale(1.25)' : 'scale(1)',
            }}
        />
    )
}
