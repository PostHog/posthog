import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import {
    IconArrowUpRight,
    IconCopy,
    IconEllipsis,
    IconFolderMove,
    IconPencil,
    IconPlus,
    IconTrash,
    IconX,
} from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { isTaggableAnalyticsType } from './analyticsFeed'
import { analyticsItemActionsLogic, analyticsItemKey } from './analyticsItemActionsLogic'
import { AnalyticsPinMenuItem } from './AnalyticsPinMenuItem'
import { analyticsShareLogic } from './analyticsShareLogic'
import { AnalyticsTagIcon } from './AnalyticsTagIcon'
import { analyticsTagsLogic } from './analyticsTagsLogic'
import { AnalyticsItem, analyticsOpenHref } from './analyticsUtils'

/** A row's own actions: open it, copy it, tag it, file it, pin it, or delete it. */
export function AnalyticsItemMenu({ item, backUrl }: { item: AnalyticsItem; backUrl: string }): JSX.Element {
    const { openShareToSpace, moveItem } = useActions(analyticsShareLogic)
    const { openTagEditor } = useActions(analyticsTagsLogic)
    const { duplicating } = useValues(analyticsItemActionsLogic)
    const { duplicateItem, openDeleteConfirm } = useActions(analyticsItemActionsLogic)
    const target = { type: item.type, ref: item.id, name: item.name }
    const { type } = item
    const taggable = isTaggableAnalyticsType(type)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="default"
                        size="icon-sm"
                        aria-label={`Actions for ${item.name}`}
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
                            disabledReason={duplicating[analyticsItemKey(item)] ? 'Duplicating...' : undefined}
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
                            onClick={() => openTagEditor({ type, ref: item.id, name: item.name, tags: item.tags })}
                            data-attr="analytics-list-row-manage-tags"
                        >
                            <AnalyticsTagIcon className="size-3.5" />
                            Manage tags
                        </DropdownMenuItem>
                    )}
                    {item.spaceName ? (
                        <>
                            <DropdownMenuItem
                                onClick={() => openShareToSpace(target)}
                                data-attr="analytics-list-row-move"
                            >
                                <IconFolderMove />
                                Move to another collection
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                variant="destructive"
                                onClick={() => moveItem(target, null)}
                                data-attr="analytics-list-row-remove-from-space"
                            >
                                <IconX />
                                Remove from collection
                            </DropdownMenuItem>
                        </>
                    ) : (
                        <DropdownMenuItem onClick={() => openShareToSpace(target)} data-attr="analytics-list-row-share">
                            <IconPlus />
                            Add to a collection
                        </DropdownMenuItem>
                    )}
                    <AnalyticsPinMenuItem
                        target={{ type: item.type, ref: item.id, name: item.name, href: item.href }}
                        dataAttr="analytics-list-row-pin"
                    />
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
