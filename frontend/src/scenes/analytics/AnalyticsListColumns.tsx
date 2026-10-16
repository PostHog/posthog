import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconFolderMove, IconFolderOpen, IconShare, IconX } from '@posthog/icons'
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

import { escapePath } from '~/layout/panel-layout/ProjectTree/utils'

import { AnalyticsOwner } from './AnalyticsOwner'
import { analyticsShareLogic } from './analyticsShareLogic'
import { AnalyticsSpaceGlyph } from './AnalyticsSpaceGlyph'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPE_INFO, AnalyticsItem, analyticsOpenHref } from './analyticsUtils'

export type AnalyticsListColumns = DataTableProps<AnalyticsItem, unknown>['columns']

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
    return [
        {
            id: 'name',
            header: 'Title',
            meta: { expand: true },
            enableSorting: false,
            cell: ({ row }) => (
                <span className="flex min-w-48 items-center gap-2 overflow-hidden">
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <span
                                    className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ color: ANALYTICS_TYPE_INFO[row.original.type].color }}
                                />
                            }
                        >
                            <AnalyticsTypeIcon type={row.original.type} />
                        </TooltipTrigger>
                        <TooltipContent>{ANALYTICS_TYPE_INFO[row.original.type].label}</TooltipContent>
                    </Tooltip>
                    <LinkPrimitive
                        to={analyticsOpenHref(row.original, backUrl)}
                        className="truncate font-semibold text-foreground"
                        data-attr={`analytics-list-row-${row.original.type}`}
                    >
                        {row.original.name}
                    </LinkPrimitive>
                </span>
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
                              <SpaceCell item={row.original} />
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
                    <TagsCell tags={row.original.tags} />
                </div>
            ),
        },
        {
            id: 'owner',
            header: 'Owner',
            enableSorting: false,
            cell: ({ row }) => <AnalyticsOwner owner={row.original.createdBy} className="w-36" />,
        },
        {
            id: 'created',
            header: 'Created',
            enableSorting: false,
            cell: ({ row }) => (
                <div className="w-24">
                    <TimeCell time={row.original.createdAt} />
                </div>
            ),
        },
        // Inside a space the Space column is gone, so the row carries the way out instead.
        ...(showSpace
            ? []
            : ([
                  {
                      id: 'move',
                      header: '',
                      enableSorting: false,
                      cell: ({ row }) => (
                          <div className="flex w-8 justify-end">
                              <MoveCell item={row.original} />
                          </div>
                      ),
                  },
              ] satisfies AnalyticsListColumns)),
    ]
}
