import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { Button, Card, DataTable, type DataTableProps, Skeleton, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import type { TicketMacroApi } from 'products/conversations/frontend/generated/api.schemas'

export function QuillMacrosTable({
    macros,
    loading,
    onCreate,
    onEdit,
    onDelete,
}: {
    macros: TicketMacroApi[]
    loading: boolean
    onCreate: () => void
    onEdit: (macro: TicketMacroApi) => void
    onDelete: (macro: TicketMacroApi) => void
}): JSX.Element {
    const columns: DataTableProps<TicketMacroApi, unknown>['columns'] = [
        {
            id: 'name',
            header: 'Name',
            meta: { expand: true },
            cell: ({ row }) => <span className="truncate">{row.original.name}</span>,
        },
        {
            id: 'shortcut',
            header: 'Shortcut',
            cell: ({ row }) => (row.original.shortcut ? `/${row.original.shortcut}` : ''),
        },
        {
            id: 'visibility',
            header: 'Visible to',
            cell: ({ row }) => (row.original.visibility === 'personal' ? 'Only you' : 'Everyone'),
        },
        {
            id: 'usage_count',
            header: 'Uses',
            meta: { align: 'right' },
            cell: ({ row }) => row.original.usage_count,
        },
        {
            id: 'last_used_at',
            header: 'Last used',
            cell: ({ row }) => (row.original.last_used_at ? <TZLabel time={row.original.last_used_at} /> : 'Never'),
        },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row }) => (
                <div className="flex justify-end gap-1">
                    <Button size="icon" aria-label="Edit" tooltip="Edit" onClick={() => onEdit(row.original)}>
                        <IconPencil />
                    </Button>
                    <Button
                        size="icon"
                        variant="destructive-outline"
                        aria-label="Delete"
                        tooltip="Delete"
                        onClick={() => onDelete(row.original)}
                    >
                        <IconTrash />
                    </Button>
                </div>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Text size="xs" variant="muted" render={<p className="m-0 max-w-160" />}>
                    Save replies you send often. Share them with your team or keep them to yourself. Insert one from a
                    ticket, or type / and its shortcut.
                </Text>
                <Button variant="primary" onClick={onCreate} data-attr="support-macro-create">
                    <IconPlus />
                    New macro
                </Button>
            </div>
            {loading && macros.length === 0 ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                </div>
            ) : (
                <Card size="sm" flush className="pt-0">
                    <DataTable columns={columns} data={macros} fullWidth size="sm" empty="No macros yet" />
                </Card>
            )}
        </div>
    )
}
