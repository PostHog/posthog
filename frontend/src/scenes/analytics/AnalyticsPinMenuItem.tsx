import { useActions, useValues } from 'kea'

import { IconPin, IconPinFilled } from '@posthog/icons'
import { DropdownMenuItem } from '@posthog/quill'

import { PinTarget, analyticsPinnedLogic, pinKey } from './analyticsPinnedLogic'

export function AnalyticsPinMenuItem({ target, dataAttr }: { target: PinTarget; dataAttr: string }): JSX.Element {
    const { pinnedShortcutIds, shortcutDataLoading } = useValues(analyticsPinnedLogic)
    const { togglePinned } = useActions(analyticsPinnedLogic)
    const pinned = pinnedShortcutIds.has(pinKey(target.type, target.ref))
    return (
        <DropdownMenuItem disabled={shortcutDataLoading} onClick={() => togglePinned(target)} data-attr={dataAttr}>
            {pinned ? <IconPinFilled /> : <IconPin />}
            {pinned ? 'Unpin from sidebar' : 'Pin to sidebar'}
        </DropdownMenuItem>
    )
}
