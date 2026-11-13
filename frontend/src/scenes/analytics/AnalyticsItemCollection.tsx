import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconFolderMove, IconFolderOpen, IconX } from '@posthog/icons'
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

import { analyticsShareLogic } from './analyticsShareLogic'
import { AnalyticsSpaceGlyph } from './AnalyticsSpaceGlyph'
import { AnalyticsItem } from './analyticsUtils'

// Long collection names would push the other columns around, so the pill stops at this many characters.
const MAX_NAME_LENGTH = 16

/**
 * The collection a row sits in, as a gray pill with the collection's colored initial and its name, opening a menu to
 * view it, move the row out of it or leave it. A row in no collection shows nothing.
 */
export function AnalyticsItemCollection({ item }: { item: AnalyticsItem }): JSX.Element | null {
    const { openShareToSpace, moveItem } = useActions(analyticsShareLogic)
    const collection = item.spaceName
    if (!collection) {
        return null
    }
    const target = { type: item.type, ref: item.id, name: item.name }
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
                <DropdownMenuItem onClick={() => openShareToSpace(target)} data-attr="analytics-list-row-move">
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
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
