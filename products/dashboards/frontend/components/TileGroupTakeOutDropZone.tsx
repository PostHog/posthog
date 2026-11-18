import clsx from 'clsx'

import { TAKE_OUT_DROP_ZONE_KEY } from '../useTileGroupDrag'

export function TileGroupTakeOutDropZone({ isDropTarget }: { isDropTarget: boolean }): JSX.Element {
    return (
        <div
            data-dashboard-section={TAKE_OUT_DROP_ZONE_KEY}
            className={clsx(
                'mb-[40vh] flex h-24 items-center justify-center rounded-lg border border-dashed text-secondary',
                isDropTarget && 'ring-2 ring-accent'
            )}
        >
            Drag a tile here to take it out of its group
        </div>
    )
}
