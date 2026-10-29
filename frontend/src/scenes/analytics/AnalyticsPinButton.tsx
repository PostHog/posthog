import { useActions, useValues } from 'kea'

import { IconPin, IconPinFilled } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { PinTarget, analyticsPinnedLogic, pinKey } from './analyticsPinnedLogic'

export function AnalyticsPinButton({
    target,
    size = 'icon-xs',
    dataAttr,
}: {
    target: PinTarget
    size?: 'icon' | 'icon-sm' | 'icon-xs'
    dataAttr: string
}): JSX.Element {
    const { pinnedShortcutIds, shortcutDataLoading } = useValues(analyticsPinnedLogic)
    const { togglePinned } = useActions(analyticsPinnedLogic)
    const pinned = pinnedShortcutIds.has(pinKey(target.type, target.ref))
    const label = pinned ? 'Unpin from sidebar' : 'Pin to sidebar'
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size={size}
                        aria-label={`${label}: ${target.name}`}
                        aria-pressed={pinned}
                        disabled={shortcutDataLoading}
                        onClick={() => togglePinned(target)}
                        data-attr={dataAttr}
                    />
                }
            >
                {pinned ? <IconPinFilled /> : <IconPin />}
            </TooltipTrigger>
            <TooltipContent>{shortcutDataLoading ? 'Updating pinned items' : label}</TooltipContent>
        </Tooltip>
    )
}
