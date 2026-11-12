import { useActions, useValues } from 'kea'

import { PinToggleButton } from './PinToggleButton'
import { PinTarget, pinTargetKey, sidebarPinsLogic } from './sidebarPinsLogic'

export function SidebarPinButton({
    target,
    size,
    dataAttr,
}: {
    target: PinTarget
    size?: 'icon' | 'icon-sm' | 'icon-xs'
    dataAttr: string
}): JSX.Element {
    const { pinnedShortcutIds, shortcutDataLoading } = useValues(sidebarPinsLogic)
    const { togglePinned } = useActions(sidebarPinsLogic)
    return (
        <PinToggleButton
            pinned={pinnedShortcutIds.has(pinTargetKey(target))}
            name={target.name}
            busy={shortcutDataLoading}
            onToggle={() => togglePinned(target)}
            size={size}
            dataAttr={dataAttr}
        />
    )
}
