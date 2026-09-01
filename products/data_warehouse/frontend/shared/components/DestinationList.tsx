import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTable, LemonTableColumn, LemonTag } from '@posthog/lemon-ui'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { DestinationIcon, destinationTypeLabel } from './DestinationIcon'

/** Where a destination writes, as far as its non-secret config says. Null when there is nothing to add. */
export function destinationTarget(destination: ExternalDataDestinationApi): string | null {
    if (destination.is_posthog_warehouse) {
        return 'Managed by PostHog'
    }
    const config = (destination.config ?? {}) as Record<string, unknown>
    const parts = [config.database, config.schema, config.dataset, config.bucket].filter(
        (part): part is string => typeof part === 'string' && part.length > 0
    )
    return parts.length > 0 ? parts.join('.') : null
}

export interface DestinationListProps {
    destinations: ExternalDataDestinationApi[]
    loading: boolean
    /** Destinations currently syncing. Rows not listed here render as off. */
    selectedIds: string[]
    onToggle: (destinationId: string) => void
    onEdit: (destination: ExternalDataDestinationApi) => void
    /** Set to make every toggle read-only, e.g. while a table inherits its source's set. */
    toggleDisabledReason?: string
}

export function DestinationList({
    destinations,
    loading,
    selectedIds,
    onToggle,
    onEdit,
    toggleDisabledReason,
}: DestinationListProps): JSX.Element {
    // Turning the last one off would leave the source syncing nowhere, which is what disabling a
    // table is for. Pin it on rather than letting the save fail.
    const isLastSelected = (id: string): boolean => selectedIds.length === 1 && selectedIds[0] === id

    const columns: LemonTableColumn<ExternalDataDestinationApi, any>[] = [
        {
            title: '',
            key: 'icon',
            width: 0,
            render: (_, destination) => <DestinationIcon type={destination.type} />,
        },
        {
            title: 'Name',
            key: 'name',
            sorter: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true }),
            render: (_, destination) => (
                <div className="flex flex-col">
                    <span className="font-semibold">{destination.name}</span>
                    {destinationTarget(destination) ? (
                        <span className="text-muted text-xs">{destinationTarget(destination)}</span>
                    ) : null}
                </div>
            ),
        },
        {
            title: 'Type',
            key: 'type',
            render: (_, destination) => (
                <LemonTag type={destination.is_posthog_warehouse ? 'highlight' : 'default'}>
                    {destinationTypeLabel(destination.type)}
                </LemonTag>
            ),
        },
        {
            title: '',
            key: 'actions',
            width: 0,
            render: (_, destination) => (
                <div className="flex gap-2 items-center justify-end">
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        onClick={() => onEdit(destination)}
                        data-attr="warehouse-destination-edit"
                        tooltip={
                            destination.is_posthog_warehouse
                                ? 'The PostHog warehouse is managed for you'
                                : 'Edit this destination'
                        }
                        disabledReason={
                            destination.is_posthog_warehouse ? 'The PostHog warehouse is managed for you' : undefined
                        }
                    />
                    <LemonSwitch
                        checked={selectedIds.includes(destination.id)}
                        onChange={() => onToggle(destination.id)}
                        data-attr="warehouse-destination-toggle"
                        disabledReason={
                            toggleDisabledReason ??
                            (isLastSelected(destination.id)
                                ? 'Pick at least one destination. To stop syncing, turn off syncing instead.'
                                : undefined)
                        }
                    />
                </div>
            ),
        },
    ]

    return (
        <LemonTable
            dataSource={destinations}
            loading={loading}
            rowKey={(destination) => destination.id}
            columns={columns}
            emptyState="No destinations yet. Add one to sync these tables somewhere besides PostHog."
        />
    )
}
