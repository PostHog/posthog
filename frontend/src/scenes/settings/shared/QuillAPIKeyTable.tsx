import type { ColumnDef } from '@tanstack/react-table'

import { IconInfo } from '@posthog/icons'
import {
    Button,
    DataTable,
    Empty,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { QuillTagList } from '../user/QuillTagList'
import { type APIKeyTableRow, formatCreatedBy } from './apiKeyTableUtils'
import { QuillAPIKeyActionsMenu } from './QuillAPIKeyActionsMenu'

function OptionalTime({ time }: { time: string | null }): JSX.Element {
    return time ? (
        <TZLabel time={time} />
    ) : (
        <Text size="xs" variant="muted" render={<span />}>
            Never
        </Text>
    )
}

export function QuillAPIKeyTable<T extends APIKeyTableRow>({
    keys,
    loading,
    noun,
    showCreatedBy,
    showActions,
    rowClassName,
    renderLabel,
    renderMaskValue,
    renderScopes,
    onEdit,
    onRoll,
    onDelete,
}: {
    keys: T[]
    loading: boolean
    noun: string
    showCreatedBy: boolean
    showActions: boolean
    rowClassName?: (key: T) => string
    renderLabel?: (key: T) => JSX.Element
    renderMaskValue?: (key: T) => JSX.Element
    renderScopes?: (key: T) => JSX.Element
    onEdit: (id: string) => void
    onRoll: (key: T) => void
    onDelete: (key: T) => void
}): JSX.Element {
    const columns: ColumnDef<T>[] = [
        {
            id: 'label',
            header: 'Label',
            enableSorting: false,
            cell: ({ row }) =>
                renderLabel ? (
                    renderLabel(row.original)
                ) : (
                    <Button
                        variant="link-foreground"
                        size="sm"
                        className="max-w-60 truncate font-semibold"
                        onClick={() => onEdit(row.original.id)}
                    >
                        {String(row.original.label)}
                    </Button>
                ),
        },
        {
            id: 'mask_value',
            header: 'Secret key',
            enableSorting: false,
            cell: ({ row }) => {
                if (renderMaskValue) {
                    return renderMaskValue(row.original)
                }

                if (row.original.mask_value) {
                    return <span className="font-mono">{row.original.mask_value}</span>
                }

                return (
                    <Tooltip>
                        <TooltipTrigger render={<span className="inline-flex cursor-default items-center gap-1" />}>
                            <span>No preview</span>
                            <IconInfo className="text-base" />
                        </TooltipTrigger>
                        <TooltipContent>This key was created before the introduction of previews</TooltipContent>
                    </Tooltip>
                )
            },
        },
        {
            id: 'scopes',
            header: 'Scopes',
            enableSorting: false,
            cell: ({ row }) =>
                renderScopes ? (
                    renderScopes(row.original)
                ) : (
                    <QuillTagList tags={row.original.scopes} onMoreClick={() => onEdit(row.original.id)} />
                ),
        },
        ...(showCreatedBy
            ? [
                  {
                      id: 'created_by',
                      header: 'Created by',
                      enableSorting: false,
                      cell: ({ row }) =>
                          row.original.created_by ? (
                              <Tooltip>
                                  <TooltipTrigger render={<span />}>
                                      {formatCreatedBy(row.original.created_by)}
                                  </TooltipTrigger>
                                  <TooltipContent>{row.original.created_by.email}</TooltipContent>
                              </Tooltip>
                          ) : (
                              'Unknown'
                          ),
                  } satisfies ColumnDef<T>,
              ]
            : []),
        {
            id: 'last_used_at',
            header: 'Last used',
            accessorFn: (key) => (key.last_used_at ? new Date(key.last_used_at).getTime() : 0),
            cell: ({ row }) => <OptionalTime time={row.original.last_used_at} />,
        },
        {
            id: 'created_at',
            header: 'Created',
            enableSorting: false,
            cell: ({ row }) => <TZLabel time={row.original.created_at} />,
        },
        {
            id: 'last_rolled_at',
            header: 'Last rolled',
            enableSorting: false,
            cell: ({ row }) => <OptionalTime time={row.original.last_rolled_at} />,
        },
        ...(showActions
            ? [
                  {
                      id: 'actions',
                      header: '',
                      enableSorting: false,
                      meta: { align: 'right' },
                      cell: ({ row }) => (
                          <QuillAPIKeyActionsMenu
                              keyLabel={row.original.label}
                              onEdit={() => onEdit(row.original.id)}
                              onRoll={() => onRoll(row.original)}
                              onDelete={() => onDelete(row.original)}
                          />
                      ),
                  } satisfies ColumnDef<T>,
              ]
            : []),
    ]

    if (loading && keys.length === 0) {
        return <Skeleton className="h-40" />
    }

    return (
        <div aria-busy={loading}>
            <DataTable
                columns={columns}
                data={keys}
                fullWidth
                getRowId={(key) => key.id}
                rowClassName={rowClassName}
                empty={
                    <Empty>
                        <EmptyHeader>
                            <EmptyTitle>{`No ${noun}s`}</EmptyTitle>
                        </EmptyHeader>
                    </Empty>
                }
            />
        </div>
    )
}
