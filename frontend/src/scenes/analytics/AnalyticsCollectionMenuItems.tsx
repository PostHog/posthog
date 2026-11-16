import { useActions } from 'kea'

import { IconFolderMove, IconX } from '@posthog/icons'
import { DropdownMenuItem } from '@posthog/quill'

import { analyticsShareLogic } from './analyticsShareLogic'
import { AnalyticsItem, analyticsItemTarget } from './analyticsUtils'

export function AnalyticsCollectionMenuItems({
    item,
    moveDataAttr,
    removeDataAttr,
}: {
    item: AnalyticsItem
    moveDataAttr: string
    removeDataAttr: string
}): JSX.Element {
    const { openShareToSpace, moveItem } = useActions(analyticsShareLogic)
    const target = analyticsItemTarget(item)

    return (
        <>
            <DropdownMenuItem onClick={() => openShareToSpace(target)} data-attr={moveDataAttr}>
                <IconFolderMove />
                Move to another collection
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onClick={() => moveItem(target, null)} data-attr={removeDataAttr}>
                <IconX />
                Remove from collection
            </DropdownMenuItem>
        </>
    )
}
