import { useValues } from 'kea'

import { maxGlobalLogic } from '../maxGlobalLogic'
import { HedgehogAvatar } from './HedgehogAvatar'

interface CollapsedFloatingMaxProps {
    onExpand: () => void
    onPositionChange: (position: any) => void
}

export function CollapsedFloatingMax({ onExpand, onPositionChange }: CollapsedFloatingMaxProps): JSX.Element {
    const { floatingMaxPosition } = useValues(maxGlobalLogic)

    return (
        <HedgehogAvatar
            onExpand={onExpand}
            isExpanded={false}
            onPositionChange={onPositionChange}
            fixedDirection={floatingMaxPosition?.side === 'left' ? 'left' : 'right'}
        />
    )
}
