import clsx from 'clsx'
import { useValues } from 'kea'

import { TOOLBAR_FIXED_POSITION_HITBOX, toolbarLogic } from './toolbarLogic'

export function ToolbarFixedZones(): JSX.Element | null {
    const { isDragging, fixedPosition, fixedPositions, lastDragPosition } = useValues(toolbarLogic)

    if (!isDragging) {
        return null
    }

    return (
        <div className="w-full h-full absolute top-0 left-0 pointer-events-none">
            {Object.entries(fixedPositions).map(([key, { x, y }]) => (
                <div
                    key={key}
                    className={clsx(
                        'transition-all absolute border rounded bg-primary opacity-20',
                        key === fixedPosition && !lastDragPosition && 'opacity-50 scale-110'
                    )}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        left: x - TOOLBAR_FIXED_POSITION_HITBOX * 0.5,
                        top: y - TOOLBAR_FIXED_POSITION_HITBOX * 0.5,
                        width: TOOLBAR_FIXED_POSITION_HITBOX,
                        height: TOOLBAR_FIXED_POSITION_HITBOX,
                    }}
                />
            ))}
        </div>
    )
}
