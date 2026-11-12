import { useActions, useValues } from 'kea'

import { IconPin, IconPinFilled } from '@posthog/icons'
import { DropdownMenuItem } from '@posthog/quill'

import { PinTarget, pinTargetKey, sidebarPinsLogic } from '~/layout/today/sidebar/sidebarPinsLogic'

export function AnalyticsPinMenuItem({ target, dataAttr }: { target: PinTarget; dataAttr: string }): JSX.Element {
    const { pinnedShortcutIds, shortcutDataLoading } = useValues(sidebarPinsLogic)
    const { togglePinned } = useActions(sidebarPinsLogic)
    const pinned = pinnedShortcutIds.has(pinTargetKey(target))
    return (
        <DropdownMenuItem disabled={shortcutDataLoading} onClick={() => togglePinned(target)} data-attr={dataAttr}>
            {pinned ? <IconPinFilled /> : <IconPin />}
            {pinned ? 'Unpin from sidebar' : 'Pin to sidebar'}
        </DropdownMenuItem>
    )
}
