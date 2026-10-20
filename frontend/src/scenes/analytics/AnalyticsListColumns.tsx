import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconEllipsis, IconFolder, IconFolderMove, IconFolderOpen, IconShare, IconTrash, IconX } from '@posthog/icons'
import {
    Button,
    Chip,
    ChipGroup,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'
import type { DataTableProps } from '@posthog/quill-components'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { escapePath } from '~/layout/panel-layout/ProjectTree/utils'

import { AnalyticsDraggableRow } from './AnalyticsDraggableRow'
import { AnalyticsFolderDropTarget } from './AnalyticsFolderDropTarget'
import type { FolderRow } from './analyticsListLogic'
import { AnalyticsOwner } from './AnalyticsOwner'
import { analyticsShareLogic } from './analyticsShareLogic'
import { AnalyticsSpaceGlyph } from './AnalyticsSpaceGlyph'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_DRAG_SCOPE, ANALYTICS_TYPE_INFO, AnalyticsItem, analyticsOpenHref } from './analyticsUtils'

export type AnalyticsListRow = { kind: 'folder'; folder: FolderRow } | { kind: 'item'; item: AnalyticsItem }

export type AnalyticsListColumns = DataTableProps<AnalyticsListRow, unknown>['columns']

function EmptyCell(): JSX.Element {
    return (
        <Text size="xs" variant="muted">
            –
        </Text>
    )
}

function TimeCell({ time, label }: { time: string | null; label?: string }): JSX.Element {
    if (!time) {
        return (
            <Text size="xs" variant="muted">
                –
            </Text>
        )
    }
    return (
        <Tooltip>
            <TooltipTrigger
                render={<span className="text-xs whitespace-nowrap text-muted-foreground" translate="no" />}
            >
                {label ? `${label} ${dayjs(time).fromNow()}` : dayjs(time).fromNow()}
            </TooltipTrigger>
            <TooltipContent>{dayjs(time).format('LLL')}</TooltipContent>
        </Tooltip>
    )
}

// Two chips fit the fixed tags column; the rest fold into a count.
const VISIBLE_TAGS = 2

function TagsCell({ tags }: { tags: string[] }): JSX.Element {
    if (!tags.length) {
        return (
            <Text size="xs" variant="muted">
                –
            </Text>
        )
    }
    const hidden = tags.length - VISIBLE_TAGS
    return (
        <ChipGroup className="flex-nowrap overflow-hidden">
            {tags.slice(0, VISIBLE_TAGS).map((tag) => (
                <Chip key={tag} size="xs" className="max-w-24 truncate">
                    {tag}
                </Chip>
            ))}
            {hidden > 0 && (
                <Text size="xs" variant="muted">
                    {`+${hidden}`}
                </Text>
            )}
        </ChipGroup>
    )
}

function SpaceCell({ item }: { item: AnalyticsItem }): JSX.Element {
    const { openShareToSpace, moveItem } = useActions(analyticsShareLogic)
    const target = { type: item.type, ref: item.id, name: item.name }
    if (!item.spaceName) {
        return (
            <Tooltip>
                <TooltipTrigger
                    render={
                        <Button
                            variant="link-muted"
                            size="xs"
                            className="h-auto gap-1 px-0 text-xs"
                            onClick={() => openShareToSpace(target)}
                            data-attr="analytics-list-row-share"
                        />
                    }
                >
                    None
                    <IconShare className="size-3" />
                </TooltipTrigger>
                <TooltipContent>Add to a collection</TooltipContent>
            </Tooltip>
        )
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="link"
                        size="xs"
                        className="h-auto max-w-full gap-1.5 px-0 text-xs text-foreground"
                        data-attr="analytics-list-row-space"
                    />
                }
            >
                <AnalyticsSpaceGlyph name={item.spaceName} />
                <span className="truncate">{item.spaceName}</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-60">
                <DropdownMenuItem
                    onClick={() =>
                        router.actions.push(urls.analyticsList({ folder: escapePath(item.spaceName ?? '') }))
                    }
                    data-attr="analytics-list-row-open-space"
                >
                    <IconFolderOpen />
                    {`Open "${item.spaceName}"`}
                </DropdownMenuItem>
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
                    {`Remove from "${item.spaceName}"`}
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function MoveCell({ item }: { item: AnalyticsItem }): JSX.Element {
    const { openShareToSpace } = useActions(analyticsShareLogic)
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Button
                        variant="default"
                        size="icon-sm"
                        aria-label="Move to another collection"
                        onClick={() => openShareToSpace({ type: item.type, ref: item.id, name: item.name })}
                        data-attr="analytics-list-row-move"
                    />
                }
            >
                <IconFolderMove />
            </TooltipTrigger>
            <TooltipContent>Move to another collection</TooltipContent>
        </Tooltip>
    )
}

function FolderMenuCell({ folder }: { folder: FolderRow }): JSX.Element | null {
    const { deleteItem } = useActions(projectTreeDataLogic)
    const entry = folder.entry
    if (!entry) {
        return null
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="default"
                        size="icon-sm"
                        aria-label={`Actions for ${folder.name}`}
                        data-attr="analytics-list-folder-menu"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-48">
                <DropdownMenuItem
                    onClick={() => router.actions.push(urls.analyticsList({ folder: folder.path }))}
                    data-attr="analytics-list-folder-open"
                >
                    <IconFolderOpen />
                    Open folder
                </DropdownMenuItem>
                <DropdownMenuItem
                    variant="destructive"
                    onClick={() => deleteItem(entry, ANALYTICS_DRAG_SCOPE)}
                    data-attr="analytics-list-folder-delete"
                >
                    <IconTrash />
                    Delete folder
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function FolderTitle({ folder, draggable }: { folder: FolderRow; draggable: boolean }): JSX.Element {
    const title = (
        <>
            <IconFolder className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <LinkPrimitive
                to={urls.analyticsList({ folder: folder.path })}
                className="truncate font-semibold text-foreground"
                data-attr="analytics-list-subfolder"
            >
                {folder.name}
            </LinkPrimitive>
        </>
    )
    return (
        <AnalyticsFolderDropTarget path={folder.path} className="flex min-w-48 items-center gap-2 overflow-hidden">
            {draggable && folder.entry ? (
                <AnalyticsDraggableRow entry={folder.entry}>{title}</AnalyticsDraggableRow>
            ) : (
                title
            )}
        </AnalyticsFolderDropTarget>
    )
}

function ItemTitle({
    item,
    backUrl,
    draggable,
}: {
    item: AnalyticsItem
    backUrl: string
    draggable: boolean
}): JSX.Element {
    const title = (
        <>
            <Tooltip>
                <TooltipTrigger
                    render={
                        <span
                            className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ color: ANALYTICS_TYPE_INFO[item.type].color }}
                        />
                    }
                >
                    <AnalyticsTypeIcon type={item.type} />
                </TooltipTrigger>
                <TooltipContent>{ANALYTICS_TYPE_INFO[item.type].label}</TooltipContent>
            </Tooltip>
            <LinkPrimitive
                to={analyticsOpenHref(item, backUrl)}
                className="truncate font-semibold text-foreground"
                data-attr={`analytics-list-row-${item.type}`}
            >
                {item.name}
            </LinkPrimitive>
        </>
    )
    return (
        <span className="flex min-w-48 items-center gap-2 overflow-hidden">
            {draggable && item.entry ? (
                <AnalyticsDraggableRow entry={item.entry}>{title}</AnalyticsDraggableRow>
            ) : (
                title
            )}
        </span>
    )
}

/**
 * The list's columns. Every column but the title has a fixed width, so the title always gets the same
 * remainder and the table does not resize as the rows change. The type shows as the title's icon.
 */
export function analyticsListColumns({
    backUrl,
    showSpace,
}: {
    backUrl: string
    showSpace: boolean
}): AnalyticsListColumns {
    const draggable = !showSpace
    return [
        {
            id: 'name',
            header: 'Title',
            meta: { expand: true },
            enableSorting: false,
            cell: ({ row }) =>
                row.original.kind === 'folder' ? (
                    <FolderTitle folder={row.original.folder} draggable={draggable} />
                ) : (
                    <ItemTitle item={row.original.item} backUrl={backUrl} draggable={draggable} />
                ),
        },
        ...(showSpace
            ? ([
                  {
                      id: 'space',
                      header: 'Collection',
                      enableSorting: false,
                      cell: ({ row }) => (
                          <div className="w-36">
                              {row.original.kind === 'item' ? <SpaceCell item={row.original.item} /> : <EmptyCell />}
                          </div>
                      ),
                  },
              ] satisfies AnalyticsListColumns)
            : []),
        {
            id: 'tags',
            header: 'Tags',
            enableSorting: false,
            cell: ({ row }) => (
                <div className="w-36 overflow-hidden">
                    {row.original.kind === 'item' ? <TagsCell tags={row.original.item.tags} /> : <EmptyCell />}
                </div>
            ),
        },
        {
            id: 'owner',
            header: 'Owner',
            enableSorting: false,
            cell: ({ row }) => (
                <AnalyticsOwner
                    owner={
                        row.original.kind === 'item'
                            ? row.original.item.createdBy
                            : (row.original.folder.createdBy ?? null)
                    }
                    className="w-36"
                />
            ),
        },
        {
            id: 'created',
            header: 'Created',
            enableSorting: false,
            cell: ({ row }) => (
                <div className="w-24">
                    <TimeCell
                        time={
                            row.original.kind === 'item'
                                ? row.original.item.createdAt
                                : (row.original.folder.createdAt ?? null)
                        }
                    />
                </div>
            ),
        },
        // Inside a collection the Collection column is gone, so the row carries the way out instead.
        ...(showSpace
            ? []
            : ([
                  {
                      id: 'move',
                      header: '',
                      enableSorting: false,
                      cell: ({ row }) => (
                          <div className="flex w-8 justify-end">
                              {row.original.kind === 'item' ? (
                                  <MoveCell item={row.original.item} />
                              ) : (
                                  <FolderMenuCell folder={row.original.folder} />
                              )}
                          </div>
                      ),
                  },
              ] satisfies AnalyticsListColumns)),
    ]
}
