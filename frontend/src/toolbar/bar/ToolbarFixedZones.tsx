import clsx from 'clsx'
import { useValues } from 'kea'

import { TOOLBAR_FIXED_POSITION_HITBOX, toolbarLogic } from './toolbarLogic'

export function ToolbarFixedZones(): JSX.Element | null {
    const { isDragging, fixedPositions } = useValues(toolbarLogic)

    if (!isDragging) {
        return null
    }

    return (
        <div className="pointer-events-none absolute left-0 top-0 h-full w-full overflow-hidden">
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
                'bg-primary absolute rounded-lg border transition-all',
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
