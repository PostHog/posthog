import { useMemo } from 'react'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import {
    Button,
    Card,
    DataTable,
    DataTableProps,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Text,
} from '@posthog/quill'

import { QuillTableSkeleton } from 'lib/components/QuillTableSkeleton/QuillTableSkeleton'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { CoreEvent } from '~/queries/schema/schema-general'

import { CATEGORY_OPTIONS, getFilterSummary, getFilterTypeLabel } from './coreEventLabels'
import { QuillCoreEventDialog, QuillCoreEventDialogProps } from './QuillCoreEventDialog'

type Columns = DataTableProps<CoreEvent, unknown>['columns']

export interface QuillCoreEventsSettingsProps extends Omit<QuillCoreEventDialogProps, 'open'> {
    coreEvents: CoreEvent[]
    loading: boolean
    dialogOpen: boolean
    onAdd: () => void
    onEdit: (event: CoreEvent) => void
    onRemove: (eventId: string) => void
}

export function QuillCoreEventsSettings({
    coreEvents,
    loading,
    dialogOpen,
    onAdd,
    onEdit,
    onRemove,
    ...dialogProps
}: QuillCoreEventsSettingsProps): JSX.Element {
    const columns = useMemo<Columns>(
        () => [
            {
                id: 'name',
                header: 'Name',
                meta: { expand: true },
                cell: ({ row }) => (
                    <Text size="xs" className="font-medium" render={<span />}>
                        {row.original.name}
                    </Text>
                ),
            },
            {
                id: 'type',
                header: 'Type',
                cell: ({ row }) => (
                    <Text size="xs" className="whitespace-nowrap" render={<span />}>
                        {getFilterTypeLabel(row.original.filter)}
                    </Text>
                ),
            },
            {
                id: 'filter',
                header: 'Filter',
                cell: ({ row }) => (
                    <Text size="xs" variant="muted" className="whitespace-nowrap" render={<span />}>
                        {getFilterSummary(row.original.filter)}
                    </Text>
                ),
            },
            {
                id: 'category',
                header: 'Category',
                cell: ({ row }) => {
                    const { category } = row.original
                    return (
                        <Text size="xs" className="whitespace-nowrap" render={<span />}>
                            {category
                                ? CATEGORY_OPTIONS.find((option) => option.value === category)?.label || category
                                : '-'}
                        </Text>
                    )
                },
            },
            {
                id: 'actions',
                header: '',
                meta: { align: 'right' },
                cell: ({ row }) => (
                    <div className="flex justify-end gap-1">
                        <Button
                            size="icon-sm"
                            tooltip="Edit"
                            aria-label={`Edit ${row.original.name}`}
                            onClick={() => onEdit(row.original)}
                        >
                            <IconPencil />
                        </Button>
                        <Button
                            variant="destructive-outline"
                            size="icon-sm"
                            tooltip="Remove"
                            aria-label={`Remove ${row.original.name}`}
                            onClick={() => onRemove(row.original.id)}
                        >
                            <IconTrash />
                        </Button>
                    </div>
                ),
            },
        ],
        [onEdit, onRemove]
    )

    const renderBody = (): JSX.Element => {
        if (loading && coreEvents.length === 0) {
            return <QuillTableSkeleton label="Loading core events" />
        }
        if (coreEvents.length === 0) {
            return (
                <Empty data-attr="core-events-empty">
                    <EmptyHeader>
                        <EmptyTitle>No core events configured</EmptyTitle>
                        <EmptyDescription>Add your first core event above.</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            )
        }
        return (
            <Card size="sm" flush className="pt-0">
                <DataTable columns={columns} data={coreEvents} fullWidth size="sm" getRowId={(event) => event.id} />
            </Card>
        )
    }

    // The event picker in the dialog reads the quill surface to render its quill version.
    return (
        <QuillSurfaceContext.Provider value>
            <SceneTitleSection
                name="Core events"
                description="Core events are key business events used across Marketing analytics, Customer analytics, and Revenue analytics."
                resourceType={{ type: 'core_event' }}
                actions={
                    <Button variant="primary" onClick={onAdd}>
                        <IconPlus />
                        Add core event
                    </Button>
                }
            />
            {renderBody()}
            <QuillCoreEventDialog open={dialogOpen} {...dialogProps} />
        </QuillSurfaceContext.Provider>
    )
}
