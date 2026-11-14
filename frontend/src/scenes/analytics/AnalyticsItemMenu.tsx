import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconArrowUpRight, IconCopy, IconEllipsis, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { AnalyticsCollectionMenuItems } from './AnalyticsCollectionMenuItems'
import { isTaggableAnalyticsType } from './analyticsFeed'
import { analyticsItemActionsLogic } from './analyticsItemActionsLogic'
import { analyticsListLogic } from './analyticsListLogic'
import { AnalyticsPinHint } from './AnalyticsPinHint'
import { AnalyticsPinMenuItem } from './AnalyticsPinMenuItem'
import { analyticsPinnedLogic } from './analyticsPinnedLogic'
import { analyticsShareLogic, shareTargetKey } from './analyticsShareLogic'
import { AnalyticsTagIcon } from './AnalyticsTagIcon'
import { analyticsTagsLogic } from './analyticsTagsLogic'
import { AnalyticsItem, analyticsItemTarget, analyticsOpenHref } from './analyticsUtils'

export function AnalyticsItemMenu({ item, backUrl }: { item: AnalyticsItem; backUrl: string }): JSX.Element {
    const { openShareToSpace } = useActions(analyticsShareLogic)
    const { openTagEditor } = useActions(analyticsTagsLogic)
    const { duplicating } = useValues(analyticsItemActionsLogic)
    const { duplicateItem, openDeleteConfirm } = useActions(analyticsItemActionsLogic)
    const target = analyticsItemTarget(item)
    const { type } = item
    const taggable = isTaggableAnalyticsType(type)
    // Read here, not passed in by the column factory: new columns would remount this cell and close its open menu.
    const { pinHintVisible } = useValues(analyticsPinnedLogic)
    const { items } = useValues(analyticsListLogic)
    const { hidePinHint } = useActions(analyticsPinnedLogic)
    const pinHint = pinHintVisible && items[0]?.type === item.type && items[0]?.id === item.id
    const [trigger, setTrigger] = useState<HTMLButtonElement | null>(null)

    return (
        <DropdownMenu onOpenChange={(open) => open && pinHint && hidePinHint()}>
            {pinHint && trigger && <AnalyticsPinHint anchor={trigger} />}
            <DropdownMenuTrigger
                render={
                    <Button
                        ref={setTrigger}
                        variant="default"
                        size="icon-sm"
                        aria-label={`Actions for ${item.name}`}
                        className={cn(pinHint && 'ring-2 ring-ring')}
                        data-attr="analytics-list-row-menu"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-56">
                <DropdownMenuGroup>
                    <DropdownMenuItem
                        onClick={() => router.actions.push(analyticsOpenHref(item, backUrl))}
                        data-attr="analytics-list-row-view"
                    >
                        <IconArrowUpRight />
                        View
                    </DropdownMenuItem>
                    {type === 'insight' && (
                        <DropdownMenuItem
                            onClick={() => router.actions.push(urls.insightEdit(item.id as InsightShortId))}
                            data-attr="analytics-list-row-edit"
                        >
                            <IconPencil />
                            Edit
                        </DropdownMenuItem>
                    )}
                    {taggable && (
                        <DropdownMenuItem
                            onClick={() => duplicateItem({ ...item, type })}
                            disabledReason={duplicating[shareTargetKey(target)] ? 'Duplicating...' : undefined}
                            data-attr="analytics-list-row-duplicate"
                        >
                            <IconCopy />
                            Duplicate
                        </DropdownMenuItem>
                    )}
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                    {taggable && (
                        <DropdownMenuItem
                            onClick={() => openTagEditor({ ...target, type })}
                            data-attr="analytics-list-row-manage-tags"
                        >
                            <AnalyticsTagIcon className="size-3.5" />
                            Manage tags
                        </DropdownMenuItem>
                    )}
                    {item.spaceName ? (
                        <AnalyticsCollectionMenuItems
                            item={item}
                            moveDataAttr="analytics-list-row-move"
                            removeDataAttr="analytics-list-row-remove-from-space"
                        />
                    ) : (
                        <DropdownMenuItem onClick={() => openShareToSpace(target)} data-attr="analytics-list-row-share">
                            <IconPlus />
                            Add to a collection
                        </DropdownMenuItem>
                    )}
                    <AnalyticsPinMenuItem target={target} dataAttr="analytics-list-row-pin" />
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    variant="destructive"
                    onClick={() => openDeleteConfirm(item)}
                    data-attr="analytics-list-row-delete"
                >
                    <IconTrash />
                    Delete
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
