import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { Badge, Button, DataTable, Empty, EmptyHeader, EmptyTitle, Skeleton, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { ReminderApi, ReminderStatusEnumApi } from 'products/reminders/frontend/generated/api.schemas'

import { QuillReminderDialog } from './QuillReminderDialog'
import { scheduleSummary } from './reminderSchedule'
import { remindersLogic } from './remindersLogic'

const STATUS_BADGE_VARIANT: Record<ReminderStatusEnumApi, 'info' | 'completed' | 'destructive'> = {
    active: 'info',
    completed: 'completed',
    errored: 'destructive',
}

export function QuillReminders({ onDelete }: { onDelete: (reminder: ReminderApi) => void }): JSX.Element {
    const { reminders, remindersLoading } = useValues(remindersLogic)
    const { setEditingReminderId } = useActions(remindersLogic)

    const columns = useMemo<ColumnDef<ReminderApi>[]>(
        () => [
            {
                id: 'title',
                header: 'Title',
                accessorKey: 'title',
                meta: { expand: true },
                cell: ({ row }) => (
                    <Text size="xs" weight="semibold" render={<span />}>
                        {row.original.title}
                    </Text>
                ),
            },
            {
                id: 'schedule',
                header: 'Schedule',
                accessorFn: (reminder) => scheduleSummary(reminder),
            },
            {
                id: 'next_fire_at',
                header: 'Next fire',
                accessorFn: (reminder) => new Date(reminder.next_fire_at ?? 0).getTime(),
                cell: ({ row }) =>
                    row.original.next_fire_at ? (
                        <TZLabel time={row.original.next_fire_at} />
                    ) : (
                        <Text size="xs" variant="muted" render={<span />}>
                            None
                        </Text>
                    ),
            },
            {
                id: 'status',
                header: 'Status',
                accessorKey: 'status',
                cell: ({ row }) => (
                    <Badge variant={STATUS_BADGE_VARIANT[row.original.status]}>
                        {capitalizeFirstLetter(row.original.status)}
                    </Badge>
                ),
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                meta: { align: 'right' },
                cell: ({ row }) => (
                    <div className="flex justify-end gap-1">
                        <Button
                            size="icon"
                            aria-label="Edit"
                            tooltip="Edit"
                            onClick={() => setEditingReminderId(row.original.id)}
                        >
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
        ],
        [setEditingReminderId, onDelete]
    )

    return (
        <div className="flex flex-col items-start gap-4">
            <Button variant="primary" onClick={() => setEditingReminderId('new')} data-attr="new-reminder">
                <IconPlus />
                New reminder
            </Button>

            {remindersLoading && reminders.length === 0 ? (
                <Skeleton className="h-40 w-full" />
            ) : (
                <div aria-busy={remindersLoading} className="w-full">
                    <DataTable
                        columns={columns}
                        data={reminders}
                        fullWidth
                        getRowId={(reminder) => reminder.id}
                        empty={
                            <Empty>
                                <EmptyHeader>
                                    <EmptyTitle>No reminders yet. Create one to get a nudge when it's due.</EmptyTitle>
                                </EmptyHeader>
                            </Empty>
                        }
                    />
                </div>
            )}

            <QuillReminderDialog />
        </div>
    )
}
