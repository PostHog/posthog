import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPlus, IconRefresh } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    DataTable,
    DataTableProps,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Heading,
    Separator,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { QuillTableSkeleton } from 'lib/components/QuillTableSkeleton/QuillTableSkeleton'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import {
    MaterializedColumnSlot,
    MaterializedColumnSlotState,
    materializedColumnsLogic,
} from './materializedColumnsLogic'
import { QuillAutoMaterializedProperties } from './QuillAutoMaterializedProperties'
import { QuillCreateSlotModal } from './QuillCreateSlotModal'
import { STATE_TOOLTIP, dmatColumnName } from './slotDisplay'

const PAGE_SIZE = 20

type Columns = DataTableProps<MaterializedColumnSlot, unknown>['columns']
type BadgeVariant = 'default' | 'warning' | 'success' | 'destructive'

const STATE_BADGE_VARIANT: Record<MaterializedColumnSlotState, BadgeVariant> = {
    [MaterializedColumnSlotState.PENDING]: 'default',
    [MaterializedColumnSlotState.BACKFILL]: 'warning',
    [MaterializedColumnSlotState.READY]: 'success',
    [MaterializedColumnSlotState.ERROR]: 'destructive',
}

/** The staff view of the materialized columns page, in quill. The scene keeps the title and the staff check. */
export function QuillMaterializedColumns(): JSX.Element | null {
    const { slots, slotsLoading, slotUsage, showCreateModal } = useValues(materializedColumnsLogic)
    const { loadSlots, setShowCreateModal, deleteSlot, retrySlot } = useActions(materializedColumnsLogic)

    const columns = useMemo<Columns>(
        () => [
            {
                id: 'property',
                header: 'Property',
                meta: { expand: true },
                cell: ({ row }) => (
                    <div className="flex min-w-0 flex-col">
                        <Text size="xs" className="font-semibold" render={<span />}>
                            {row.original.property_definition_details?.name}
                        </Text>
                        <Text size="xs" variant="muted" render={<span />}>
                            <span>ID:&nbsp;</span>
                            <span translate="no">{row.original.property_definition}</span>
                        </Text>
                    </div>
                ),
            },
            {
                id: 'column',
                header: 'Column',
                cell: ({ row }) =>
                    // PENDING slots have no column assigned yet, because the weekly cron picks one.
                    row.original.slot_index === null || row.original.slot_index === undefined ? (
                        <Text size="xs" variant="muted" className="italic" render={<span />}>
                            awaiting next weekly cycle
                        </Text>
                    ) : (
                        <Text size="xs" className="font-mono" render={<span />}>
                            {dmatColumnName(row.original.slot_index)}
                        </Text>
                    ),
            },
            {
                id: 'state',
                header: 'State',
                cell: ({ row }) => {
                    const state = row.original.state as MaterializedColumnSlotState
                    return (
                        <Tooltip>
                            <TooltipTrigger render={<span className="inline-flex" />}>
                                <Badge variant={STATE_BADGE_VARIANT[state] ?? 'default'} className="uppercase">
                                    {row.original.state}
                                </Badge>
                            </TooltipTrigger>
                            <TooltipContent className="max-w-80">{STATE_TOOLTIP[state] ?? ''}</TooltipContent>
                        </Tooltip>
                    )
                },
            },
            {
                id: 'error',
                header: 'Error',
                cell: ({ row }) =>
                    row.original.error_message ? (
                        <Tooltip>
                            <TooltipTrigger render={<span className="block max-w-xs truncate" />}>
                                <Text size="xs" className="text-destructive-foreground" render={<span />}>
                                    {row.original.error_message}
                                </Text>
                            </TooltipTrigger>
                            <TooltipContent className="max-w-96">{row.original.error_message}</TooltipContent>
                        </Tooltip>
                    ) : (
                        <Text size="xs" variant="muted" render={<span />}>
                            —
                        </Text>
                    ),
            },
            {
                id: 'created_at',
                header: 'Created',
                cell: ({ row }) => (
                    <Text size="xs" className="whitespace-nowrap" render={<span />}>
                        {humanFriendlyDetailedTime(row.original.created_at)}
                    </Text>
                ),
            },
            {
                id: 'actions',
                header: '',
                meta: { align: 'right' },
                cell: ({ row }) => (
                    <div className="flex justify-end gap-2">
                        {row.original.state === MaterializedColumnSlotState.ERROR && (
                            <Button variant="outline" size="sm" onClick={() => retrySlot(row.original.id)}>
                                Retry
                            </Button>
                        )}
                        <Button
                            variant="destructive-outline"
                            size="sm"
                            onClick={() => deleteSlot(row.original.id)}
                            disabledReason={
                                row.original.state === MaterializedColumnSlotState.BACKFILL
                                    ? 'Cannot delete while the backfill mutation is in flight — wait for it to complete or fail'
                                    : undefined
                            }
                        >
                            Delete
                        </Button>
                    </div>
                ),
            },
        ],
        [deleteSlot, retrySlot]
    )

    if (!slotUsage) {
        return null
    }

    const paginated = slots.length > PAGE_SIZE

    return (
        <div className="flex flex-col gap-6">
            <Card>
                <CardHeader>
                    <CardTitle>Slot usage</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                    <div className="grid grid-cols-2 gap-4">
                        <div className="flex flex-col gap-1">
                            <Text size="xs" className="font-semibold" render={<span />}>
                                Used
                            </Text>
                            <Heading size="xl" render={<span className="m-0" translate="no" />}>
                                {slotUsage.used_total} / {slotUsage.max_slots_per_team}
                            </Heading>
                        </div>
                        <div className="flex flex-col gap-1">
                            <Text size="xs" className="font-semibold" render={<span />}>
                                Available
                            </Text>
                            <Heading size="xl" render={<span className="m-0" />}>
                                {slotUsage.available}
                            </Heading>
                        </div>
                    </div>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Cap is team-wide. Newly assigned properties stay PENDING until the next weekly backfill cycle.
                    </Text>
                </CardContent>
            </Card>

            <Separator />

            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Heading size="base" render={<h3 className="m-0" />}>
                        Materialized slots
                    </Heading>
                    <div className="flex flex-wrap gap-2">
                        <Button variant="outline" onClick={loadSlots} loading={slotsLoading}>
                            <IconRefresh />
                            Refresh
                        </Button>
                        <Button
                            variant="primary"
                            onClick={() => setShowCreateModal(true)}
                            disabledReason={
                                slotUsage.available <= 0
                                    ? `Team is at the cap of ${slotUsage.max_slots_per_team} slots`
                                    : undefined
                            }
                        >
                            <IconPlus />
                            Assign slot
                        </Button>
                    </div>
                </div>
                {slotsLoading && slots.length === 0 ? (
                    <QuillTableSkeleton label="Loading materialized slots" />
                ) : slots.length === 0 ? (
                    <Empty data-attr="materialized-slots-empty">
                        <EmptyHeader>
                            <EmptyTitle>No materialized slots</EmptyTitle>
                            <EmptyDescription>
                                No materialized slots assigned yet. Click 'Assign slot' to get started.
                            </EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                ) : (
                    <Card size="sm" flush className="pt-0">
                        <div data-attr="materialized-slots-table">
                            <DataTable
                                // The pager shows only past one page. A list that shrinks to one page remounts, or
                                // the table keeps paging it.
                                key={paginated ? 'paginated' : 'single-page'}
                                columns={columns}
                                data={slots}
                                fullWidth
                                size="sm"
                                pageSize={paginated ? PAGE_SIZE : undefined}
                                getRowId={(slot) => slot.id}
                            />
                        </div>
                    </Card>
                )}
            </div>

            <Separator />

            <QuillAutoMaterializedProperties />

            {showCreateModal && <QuillCreateSlotModal />}
        </div>
    )
}
