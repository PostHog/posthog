import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconFolderOpen, IconPlus } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { urls } from 'scenes/urls'

import { escapePath } from '~/layout/panel-layout/ProjectTree/utils'

import { AnalyticsCollectionMenuItems } from './AnalyticsCollectionMenuItems'
import { analyticsShareLogic } from './analyticsShareLogic'
import { AnalyticsSpaceGlyph } from './AnalyticsSpaceGlyph'
import { AnalyticsItem, analyticsItemTarget, ROW_HOVER_REVEAL } from './analyticsUtils'

// Long collection names would push the other columns around, so the pill stops at this many characters.
const MAX_NAME_LENGTH = 16

export function AnalyticsItemCollection({ item }: { item: AnalyticsItem }): JSX.Element {
    const { openShareToSpace } = useActions(analyticsShareLogic)
    const collection = item.spaceName
    if (!collection) {
        return (
            <Button
                variant="default"
                size="icon-xs"
                tooltip="Add to a collection"
                aria-label={`Add ${item.name} to a collection`}
                className={ROW_HOVER_REVEAL}
                onClick={() => openShareToSpace(analyticsItemTarget(item))}
                data-attr="analytics-list-row-space-add"
            >
                <IconPlus />
            </Button>
        )
    }
    const label = collection.length > MAX_NAME_LENGTH ? `${collection.slice(0, MAX_NAME_LENGTH)}…` : collection

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        size="xs"
                        title={collection}
                        className="shrink-0 gap-1 pl-1"
                        data-attr="analytics-list-row-space"
                    />
                }
            >
                <AnalyticsSpaceGlyph name={collection} className="rounded-full" />
                <span className="whitespace-nowrap">{label}</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-60">
                <DropdownMenuGroup>
                    <DropdownMenuLabel className="flex items-center gap-2 normal-case">
                        <AnalyticsSpaceGlyph name={collection} className="rounded-full" />
                        <span className="truncate">{collection}</span>
                    </DropdownMenuLabel>
                    <DropdownMenuItem
                        onClick={() => router.actions.push(urls.analyticsList({ folder: escapePath(collection) }))}
                        data-attr="analytics-list-row-open-space"
                    >
                        <IconFolderOpen />
                        <span className="truncate">{`View ${collection}`}</span>
                    </DropdownMenuItem>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <AnalyticsCollectionMenuItems
                    item={item}
                    moveDataAttr="analytics-list-row-space-move"
                    removeDataAttr="analytics-list-row-space-remove"
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
