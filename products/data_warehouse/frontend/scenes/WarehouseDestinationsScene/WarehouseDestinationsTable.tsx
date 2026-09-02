import type { ReactNode } from 'react'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumn, LemonTag } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { DestinationIcon, destinationTypeLabel } from '../../shared/components/DestinationIcon'
import { destinationTarget } from '../../shared/components/destinationTarget'
import { SyncedSources } from './SyncedSources'

const MANAGED_REASON = 'The PostHog warehouse is managed for you'

export interface WarehouseDestinationsTableProps {
    destinations: ExternalDataDestinationApi[]
    loading: boolean
    onEdit: (destination: ExternalDataDestinationApi) => void
    onDelete: (destination: ExternalDataDestinationApi) => void
    /** The destination currently being deleted, so its row cannot fire a second request. */
    deletingId?: string | null
    /** Rendered when the list has loaded and holds nothing. */
    emptyState?: ReactNode
}

export function WarehouseDestinationsTable({
    destinations,
    loading,
    onEdit,
    onDelete,
    deletingId,
    emptyState,
}: WarehouseDestinationsTableProps): JSX.Element {
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
            title: 'Synced by',
            key: 'synced_sources',
            render: (_, destination) => <SyncedSources destination={destination} />,
        },
        updatedAtColumn() as LemonTableColumn<ExternalDataDestinationApi, any>,
        {
            title: '',
            key: 'actions',
            width: 0,
            render: (_, destination) => {
                const managedReason = destination.is_posthog_warehouse ? MANAGED_REASON : undefined
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    fullWidth
                                    icon={<IconPencil />}
                                    onClick={() => onEdit(destination)}
                                    data-attr="warehouse-destination-scene-edit"
                                    disabledReason={managedReason}
                                >
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    fullWidth
                                    status="danger"
                                    icon={<IconTrash />}
                                    onClick={() => onDelete(destination)}
                                    data-attr="warehouse-destination-scene-delete"
                                    disabledReason={
                                        managedReason ??
                                        (deletingId === destination.id ? 'Deleting this destination' : undefined)
                                    }
                                >
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <LemonTable
            dataSource={destinations}
            loading={loading}
            rowKey={(destination) => destination.id}
            columns={columns}
            nouns={['destination', 'destinations']}
            emptyState={emptyState}
        />
    )
}
