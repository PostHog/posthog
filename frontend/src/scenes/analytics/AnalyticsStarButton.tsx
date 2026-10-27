import { useActions, useValues } from 'kea'

import { IconStar, IconStarFilled } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { StarTarget, analyticsStarredLogic, starKey } from './analyticsStarredLogic'

export function AnalyticsStarButton({
    target,
    size = 'icon-xs',
    dataAttr,
}: {
    target: StarTarget
    size?: 'icon' | 'icon-sm' | 'icon-xs'
    dataAttr: string
}): JSX.Element {
    const { starredShortcutIds, shortcutDataLoading } = useValues(analyticsStarredLogic)
    const { toggleStarred } = useActions(analyticsStarredLogic)
    const starred = starredShortcutIds.has(starKey(target.type, target.ref))
    const label = starred ? 'Remove from starred' : 'Add to starred'
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size={size}
                        aria-label={`${label}: ${target.name}`}
                        aria-pressed={starred}
                        disabled={shortcutDataLoading}
                        onClick={() => toggleStarred(target)}
                        data-attr={dataAttr}
                    />
                }
            >
                {starred ? <IconStarFilled /> : <IconStar />}
            </TooltipTrigger>
            <TooltipContent>{shortcutDataLoading ? 'Updating starred' : label}</TooltipContent>
        </Tooltip>
    )
}
