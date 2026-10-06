import { Chip, ChipGroup, DataTableProps, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AnalyticsOwner } from './AnalyticsOwner'
import { AnalyticsTypeIcon } from './AnalyticsTypeIcon'
import { ANALYTICS_TYPE_INFO, AnalyticsItem, analyticsOpenHref } from './analyticsUtils'

// Two chips fit the fixed tags column; the rest fold into a count.
const VISIBLE_TAGS = 2

export type AnalyticsListColumns = DataTableProps<AnalyticsItem, unknown>['columns']

function TimeCell({ time, label }: { time: string | null; label?: string }): JSX.Element {
    if (!time) {
        return (
            <Text size="sm" variant="muted">
                –
            </Text>
        )
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="text-sm whitespace-nowrap" translate="no" />}>
                {label ? `${label} ${dayjs(time).fromNow()}` : dayjs(time).fromNow()}
            </TooltipTrigger>
            <TooltipContent>{dayjs(time).format('LLL')}</TooltipContent>
        </Tooltip>
    )
}

function TagsCell({ tags }: { tags: string[] }): JSX.Element {
    if (!tags.length) {
        return (
            <Text size="sm" variant="muted">
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

/**
 * The list's columns. Every column but the title has a fixed width, so the title always gets the same
 * remainder and the table does not resize as the rows change.
 */
export function analyticsListColumns({
    backUrl,
    showType,
}: {
    backUrl: string
    showType: boolean
}): AnalyticsListColumns {
    return [
        {
            id: 'name',
            header: 'Title',
            meta: { expand: true },
            enableSorting: false,
            cell: ({ row }) => (
                <span className="flex min-w-48 items-center gap-2 overflow-hidden">
                    <span className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4" aria-hidden>
                        <AnalyticsTypeIcon type={row.original.type} />
                    </span>
                    <LinkPrimitive
                        to={analyticsOpenHref(row.original, backUrl)}
                        className="truncate font-semibold text-foreground"
                        data-attr={`analytics-list-row-${row.original.type}`}
                    >
                        {row.original.name}
                    </LinkPrimitive>
                    {row.original.spaceName && (
                        <Text size="xs" variant="muted" className="shrink-0 truncate">
                            {`#${row.original.spaceName}`}
                        </Text>
                    )}
                </span>
            ),
        },
        {
            id: 'owner',
            header: 'Owner',
            enableSorting: false,
            cell: ({ row }) => <AnalyticsOwner owner={row.original.createdBy} className="w-32" />,
        },
        // A single-type list repeats the type on every row, so the column goes and the title gets the room.
        ...(showType
            ? ([
                  {
                      id: 'type',
                      header: 'Type',
                      enableSorting: false,
                      cell: ({ row }) => (
                          <Text size="sm" className="block w-20">
                              {ANALYTICS_TYPE_INFO[row.original.type].label}
                          </Text>
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
            id: 'created',
            header: 'Created',
            enableSorting: false,
            cell: ({ row }) => (
                <div className="w-24">
                    <TimeCell time={row.original.createdAt} />
                </div>
            ),
        },
        {
            id: 'accessed',
            header: 'Last accessed',
            enableSorting: false,
            // Only dashboards and insights record a project-wide access time, so the others show their best-known time.
            cell: ({ row }) => (
                <div className="w-28">
                    {row.original.lastAccessedAt ? (
                        <TimeCell time={row.original.lastAccessedAt} />
                    ) : (
                        <TimeCell time={row.original.timestamp} label={row.original.timestampLabel} />
                    )}
                </div>
            ),
        },
    ]
}
