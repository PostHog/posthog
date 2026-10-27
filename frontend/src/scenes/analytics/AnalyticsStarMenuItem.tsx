import { useActions, useValues } from 'kea'

import { IconStar, IconStarFilled } from '@posthog/icons'
import { DropdownMenuItem } from '@posthog/quill'

import { StarTarget, analyticsStarredLogic, starKey } from './analyticsStarredLogic'

export function AnalyticsStarMenuItem({ target, dataAttr }: { target: StarTarget; dataAttr: string }): JSX.Element {
    const { starredShortcutIds, shortcutDataLoading } = useValues(analyticsStarredLogic)
    const { toggleStarred } = useActions(analyticsStarredLogic)
    const starred = starredShortcutIds.has(starKey(target.type, target.ref))
    return (
        <DropdownMenuItem disabled={shortcutDataLoading} onClick={() => toggleStarred(target)} data-attr={dataAttr}>
            {starred ? <IconStarFilled /> : <IconStar />}
            {starred ? 'Remove from starred' : 'Add to starred'}
        </DropdownMenuItem>
    )
}
