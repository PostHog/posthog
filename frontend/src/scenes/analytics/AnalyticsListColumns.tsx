import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import {
    IconChevronDown,
    IconEllipsis,
    IconFolder,
    IconFolderMove,
    IconFolderOpen,
    IconPeople,
    IconTrash,
    IconX,
} from '@posthog/icons'
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

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { escapePath } from '~/layout/panel-layout/ProjectTree/utils'

import { AnalyticsDraggableRow } from './AnalyticsDraggableRow'
import { AnalyticsFolderDropTarget } from './AnalyticsFolderDropTarget'
import { analyticsListLogic } from './analyticsListLogic'
import type { FolderRow } from './analyticsListLogic'
import { AnalyticsOwner } from './AnalyticsOwner'
import { AnalyticsPinMenuItem } from './AnalyticsPinMenuItem'
import { analyticsShareLogic } from './analyticsShareLogic'
import { AnalyticsSpaceGlyph } from './AnalyticsSpaceGlyph'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import {
    ANALYTICS_DRAG_SCOPE,
    ANALYTICS_TYPE_INFO,
    AnalyticsItem,
    analyticsOpenHref,
    isSpacePath,
} from './analyticsUtils'
import { analyticsViewersLogic } from './analyticsViewersLogic'

export type AnalyticsListRow = { kind: 'folder'; folder: FolderRow } | { kind: 'item'; item: AnalyticsItem }

export type AnalyticsListColumns = ColumnDef<AnalyticsListRow>[]

/** The column the list is sorted on, the only one of the sortable columns it shows. */
export type AnalyticsSortColumn = 'last_viewed_at' | 'created_at' | 'view_count' | 'viewer_count'

function EmptyCell(): JSX.Element {
    return (
        <Text size="xs" variant="muted">
            –
        </Text>
    )
}

function TimeCell({ time }: { time: string | null }): JSX.Element {
    if (!time) {
        return <EmptyCell />
    }
    return (
        <Text size="xs" variant="muted" render={<span />}>
            <TZLabel time={time} />
        </Text>
    )
}

function CountCell({
    item,
    count,
    source,
}: {
    item: AnalyticsItem
    count: number
    source: 'views' | 'viewers'
}): JSX.Element {
    const { openViewers } = useActions(analyticsViewersLogic)
    if (!count) {
        return (
            <Text size="xs" variant="muted">
                0
            </Text>
        )
    }
    return (
        <Button
            variant="link"
            size="sm"
            tooltip="See who viewed it"
            onClick={() => openViewers({ type: item.type, ref: item.id, name: item.name }, source)}
            data-attr={`analytics-list-row-${source}`}
        >
            {count.toLocaleString()}
        </Button>
    )
}

// Two chips fit the fixed tags column; the rest fold into a count.
const VISIBLE_TAGS = 2

function TagsCell({ tags }: { tags: string[] }): JSX.Element {
    const { filters } = useValues(analyticsListLogic)
    const { setFilters } = useActions(analyticsListLogic)
    if (!tags.length) {
        return (
            <Text size="xs" variant="muted">
                –
            </Text>
        )
    }
    const hidden = tags.length - VISIBLE_TAGS
    return (
        <div className="flex min-w-0 items-center gap-1">
            <ChipGroup className="min-w-0 max-w-full flex-1 flex-nowrap">
                {tags.slice(0, VISIBLE_TAGS).map((tag) => (
                    <Chip
                        key={tag}
                        size="xs"
                        className="min-w-0 max-w-24 flex-1"
                        title={`Filter by ${tag}`}
                        render={<button type="button" />}
                        onClick={() => {
                            if (!filters.tags.includes(tag)) {
                                setFilters({ tags: [...filters.tags, tag] })
                            }
                        }}
                        data-attr="analytics-list-row-tag"
                    >
                        <span className="min-w-0 truncate">{tag}</span>
                    </Chip>
                ))}
            </ChipGroup>
            {hidden > 0 && (
                <Text size="xs" variant="muted" className="shrink-0">
                    {`+${hidden}`}
                </Text>
            )}
        </div>
    )
}

function SpaceCell({ item }: { item: AnalyticsItem }): JSX.Element {
    const { openShareToSpace, moveItem } = useActions(analyticsShareLogic)
    const target = { type: item.type, ref: item.id, name: item.name }
    if (!item.spaceName) {
        return (
            <Button
                size="sm"
                tooltip="Add to a collection"
                onClick={() => openShareToSpace(target)}
                data-attr="analytics-list-row-share"
            >
                None
                <IconChevronDown />
            </Button>
        )
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button size="sm" data-attr="analytics-list-row-space" />}>
                <AnalyticsSpaceGlyph name={item.spaceName} />
                <span>{item.spaceName}</span>
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-60">
                <DropdownMenuItem
                    onClick={() =>
                        router.actions.push(urls.analyticsList({ folder: escapePath(item.spaceName ?? '') }))
                    }
                    data-attr="analytics-list-row-open-space"
                >
                    <IconFolderOpen />
                    <span>{`Open "${item.spaceName}"`}</span>
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

function ItemMenuCell({ item }: { item: AnalyticsItem }): JSX.Element {
    const { openShareToSpace } = useActions(analyticsShareLogic)
    const { openViewers } = useActions(analyticsViewersLogic)
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
                <AnalyticsPinMenuItem
                    target={{ type: item.type, ref: item.id, name: item.name, href: item.href }}
                    dataAttr="analytics-list-row-pin"
                />
                <DropdownMenuItem
                    onClick={() => openShareToSpace({ type: item.type, ref: item.id, name: item.name })}
                    data-attr="analytics-list-row-move"
                >
                    <IconFolderMove />
                    Move to another collection
                </DropdownMenuItem>
                <DropdownMenuItem
                    onClick={() => openViewers({ type: item.type, ref: item.id, name: item.name }, 'menu')}
                    data-attr="analytics-list-row-usage"
                >
                    <IconPeople />
                    View usage
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
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
                {isSpacePath(folder.path) && (
                    <AnalyticsPinMenuItem
                        target={{ type: 'folder', ref: folder.path, name: folder.name }}
                        dataAttr="analytics-list-folder-pin"
                    />
                )}
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
            <Button
                variant="link-foreground"
                size="sm"
                nativeButton={false}
                left
                render={<LinkPrimitive to={urls.analyticsList({ folder: folder.path })} />}
                className="min-w-0 shrink"
                data-attr="analytics-list-subfolder"
            >
                <span className="truncate">{folder.name}</span>
            </Button>
        </>
    )
    return (
        <AnalyticsFolderDropTarget path={folder.path} className="flex items-center">
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
    position,
}: {
    item: AnalyticsItem
    backUrl: string
    draggable: boolean
    position: number
}): JSX.Element {
    const { itemOpened } = useActions(analyticsListLogic)
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
            <Button
                variant="link-foreground"
                size="sm"
                nativeButton={false}
                left
                render={<LinkPrimitive to={analyticsOpenHref(item, backUrl)} />}
                className="min-w-0 shrink"
                data-attr={`analytics-list-row-${item.type}`}
                // Capture-phase, so Cmd/Ctrl-clicks count too: the link's own handler returns
                // for those before it calls onClick. Middle-clicks only fire auxclick.
                onClickCapture={() => itemOpened(item, position)}
                onAuxClick={(event) => event.button === 1 && itemOpened(item, position)}
            >
                <span className="truncate">{item.name}</span>
            </Button>
        </>
    )
    return (
        <span className="flex items-center">
            {draggable && item.entry ? (
                <AnalyticsDraggableRow entry={item.entry}>{title}</AnalyticsDraggableRow>
            ) : (
                title
            )}
        </span>
    )
}

function sortColumn(id: AnalyticsSortColumn, sortable: boolean): AnalyticsListColumns[number] {
    switch (id) {
        case 'last_viewed_at':
            return {
                id,
                header: 'Last viewed by me',
                accessorFn: (row) => (row.kind === 'item' ? (row.item.entry?.last_viewed_at ?? null) : null),
                enableSorting: sortable,
                sortDescFirst: true,
                enableMultiSort: false,
                meta: { sortDataAttr: 'analytics-list-sort-last-viewed' },
                cell: ({ getValue }) => <TimeCell time={getValue<string | null>()} />,
            }
        case 'created_at':
            return {
                id,
                header: 'Created',
                accessorFn: (row) => (row.kind === 'item' ? row.item.createdAt : (row.folder.createdAt ?? null)),
                enableSorting: sortable,
                sortDescFirst: true,
                enableMultiSort: false,
                meta: { sortDataAttr: 'analytics-list-sort-created' },
                cell: ({ getValue }) => <TimeCell time={getValue<string | null>()} />,
            }
        case 'view_count':
        case 'viewer_count':
            return {
                id,
                header: id === 'view_count' ? 'Views' : 'Viewers',
                // The counts only sort most first, which the sort menu picks, so the header does not toggle them.
                enableSorting: false,
                cell: ({ row }) =>
                    row.original.kind === 'item' ? (
                        <CountCell
                            item={row.original.item}
                            count={
                                (id === 'view_count' ? row.original.item.viewCount : row.original.item.viewerCount) ?? 0
                            }
                            source={id === 'view_count' ? 'views' : 'viewers'}
                        />
                    ) : (
                        <EmptyCell />
                    ),
            }
    }
}

/** The list's columns. The type shows as the title's icon. Of the sortable columns, only the sorted one shows. */
export function analyticsListColumns({
    backUrl,
    showSpace,
    showOwner,
    sortedColumn,
}: {
    backUrl: string
    showSpace: boolean
    showOwner: boolean
    /** Null for a folder, which lists by name and shows when each row was created. */
    sortedColumn: AnalyticsSortColumn | null
}): AnalyticsListColumns {
    const draggable = !showSpace
    return [
        {
            id: 'name',
            minSize: 256,
            header: 'Title',
            meta: { expand: true },
            enableSorting: false,
            cell: ({ row }) =>
                row.original.kind === 'folder' ? (
                    <FolderTitle folder={row.original.folder} draggable={draggable} />
                ) : (
                    <ItemTitle item={row.original.item} backUrl={backUrl} draggable={draggable} position={row.index} />
                ),
        },
        ...(showSpace
            ? ([
                  {
                      id: 'space',
                      header: 'Collection',
                      enableSorting: false,
                      cell: ({ row }) =>
                          row.original.kind === 'item' ? <SpaceCell item={row.original.item} /> : <EmptyCell />,
                  },
              ] satisfies AnalyticsListColumns)
            : []),
        {
            id: 'tags',
            header: 'Tags',
            enableSorting: false,
            cell: ({ row }) =>
                row.original.kind === 'item' ? <TagsCell tags={row.original.item.tags} /> : <EmptyCell />,
        },
        ...(showOwner
            ? ([
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
                          />
                      ),
                  },
              ] satisfies AnalyticsListColumns)
            : []),
        sortedColumn ? sortColumn(sortedColumn, true) : sortColumn('created_at', false),
        {
            id: 'actions',
            enableResizing: false,
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row }) =>
                row.original.kind === 'item' ? (
                    <ItemMenuCell item={row.original.item} />
                ) : (
                    <FolderMenuCell folder={row.original.folder} />
                ),
        },
    ]
}
