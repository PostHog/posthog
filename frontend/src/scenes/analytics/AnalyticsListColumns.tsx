import { useActions } from 'kea'

import { IconShare } from '@posthog/icons'
import { Button, DataTableProps, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

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

function SpaceCell({ item }: { item: AnalyticsItem }): JSX.Element {
    const { openShareToSpace } = useActions(analyticsShareLogic)
    if (!item.spaceName) {
        return (
            <Tooltip>
                <TooltipTrigger
                    render={
                        <Button
                            variant="link-muted"
                            size="xs"
                            className="h-auto gap-1 px-0 text-xs"
                            onClick={() => openShareToSpace({ type: item.type, ref: item.id, name: item.name })}
                            data-attr="analytics-list-row-share"
                        />
                    }
                >
                    Personal
                    <IconShare className="size-3" />
                </TooltipTrigger>
                <TooltipContent>Share into a space</TooltipContent>
            </Tooltip>
        )
    }
    return (
        <LinkPrimitive
            to={urls.analyticsList({ folder: item.spaceName })}
            className="flex min-w-0 items-center gap-1.5 text-xs text-foreground"
            data-attr="analytics-list-row-space"
        >
            <AnalyticsSpaceGlyph name={item.spaceName} />
            <span className="truncate">{item.spaceName}</span>
        </LinkPrimitive>
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
                      header: 'Space',
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
        {
            id: 'accessed',
            header: 'Last viewed',
            enableSorting: false,
            cell: ({ row }) => (
                <div className="w-28">
                    <TimeCell time={row.original.lastAccessedAt} />
                </div>
            ),
        },
    ]
}
