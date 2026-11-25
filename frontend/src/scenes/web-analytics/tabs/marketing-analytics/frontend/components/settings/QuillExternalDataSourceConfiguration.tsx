import type { ColumnDef } from '@tanstack/react-table'

import { IconGear, IconPencil, IconTrash } from '@posthog/icons'
import { Badge, Button, DataTable, Heading, Item, ItemContent, ItemDescription, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ExternalDataSource } from '~/types'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'
import { AddIntegrationButton } from 'products/marketing_analytics/frontend/components/AddIntegrationButton'

import { ExternalTable } from '../../logic/marketingAnalyticsLogic'
import { MAX_ITEMS_TO_SHOW, nativeSourceDisplayLabel } from '../../logic/utils'
import { ColumnMappingModal } from './ColumnMappingModal'
import type { UnifiedSource } from './ExternalDataSourceConfiguration'
import { ItemName } from './PaginationControls'
import { QuillListDisplay } from './QuillListDisplay'
import { QuillPaginationControls } from './QuillPaginationControls'
import { QuillStatusIcon } from './QuillStatusIcon'

function sourceTypeBadgeVariant(label: UnifiedSource['sourceTypeLabel']): 'success' | 'info' | 'default' {
    if (label === 'Native') {
        return 'success'
    }
    if (label === 'Self-managed') {
        return 'info'
    }
    return 'default'
}

function ConfigurationCell({ item }: { item: UnifiedSource }): JSX.Element {
    if (item.isNative && item.syncingTables && item.tablesToSync) {
        return (
            <div className="flex flex-col gap-1">
                {item.syncingTables.length > 0 && (
                    <div className="flex flex-col">
                        <Text size="xs" variant="muted" render={<span />}>
                            Syncing:
                        </Text>
                        <QuillListDisplay list={item.syncingTables} />
                    </div>
                )}
                {item.tablesToSync.length > 0 && (
                    <div className="flex flex-col">
                        <Text size="xs" variant="muted" render={<span />}>
                            To sync:
                        </Text>
                        <QuillListDisplay list={item.tablesToSync} />
                    </div>
                )}
                {item.syncingTables.length === 0 && item.tablesToSync.length === 0 && (
                    <Text size="xs" variant="muted" render={<span />}>
                        No tables required
                    </Text>
                )}
            </div>
        )
    }

    if (item.isTable && item.table) {
        const mappedFields = item.table.source_map ? Object.keys(item.table.source_map).length : 0

        return mappedFields > 0 ? (
            <Text size="xs" render={<span />}>{`${mappedFields} columns mapped`}</Text>
        ) : (
            <Text size="xs" variant="muted" render={<span />}>
                No columns mapped
            </Text>
        )
    }

    return (
        <Text size="xs" variant="muted" render={<span />}>
            -
        </Text>
    )
}

export function QuillExternalDataSourceConfiguration({
    displayedSources,
    totalCount,
    hasMoreSources,
    showAll,
    onToggleShowAll,
    loading,
    hasNoConfiguredSources,
    unconfiguredNativeSources,
    restrictedReason,
    editingTable,
    onEditTable,
    onRemoveTableMapping,
    hasAnyMapping,
}: {
    displayedSources: UnifiedSource[]
    totalCount: number
    hasMoreSources: boolean
    showAll: boolean
    onToggleShowAll: () => void
    loading: boolean
    hasNoConfiguredSources: boolean
    unconfiguredNativeSources: ExternalDataSource[]
    restrictedReason: string | null
    editingTable: ExternalTable | null
    onEditTable: (table: ExternalTable | null) => void
    onRemoveTableMapping: (table: ExternalTable) => void
    hasAnyMapping: (table: ExternalTable) => boolean
}): JSX.Element {
    const columns: ColumnDef<UnifiedSource>[] = [
        {
            id: 'icon',
            header: '',
            cell: ({ row }) => (
                <SourceIcon
                    type={row.original.nativeSource?.source_type || row.original.table?.source_type || ''}
                    engine={row.original.nativeSource?.engine}
                />
            ),
        },
        {
            id: 'name',
            header: 'Name',
            meta: { expand: true },
            cell: ({ row }) =>
                row.original.sourceUrl ? (
                    <Button
                        variant="link-foreground"
                        size="sm"
                        nativeButton={false}
                        render={<LinkPrimitive to={row.original.sourceUrl} />}
                    >
                        {row.original.name}
                    </Button>
                ) : (
                    <span>{row.original.name}</span>
                ),
        },
        {
            id: 'type',
            header: 'Type',
            cell: ({ row }) => (
                <Badge variant={sourceTypeBadgeVariant(row.original.sourceTypeLabel)}>
                    {row.original.sourceTypeLabel}
                </Badge>
            ),
        },
        {
            id: 'source',
            header: 'Source',
            cell: ({ row }) => row.original.sourceType,
        },
        {
            id: 'config',
            header: 'Configuration',
            cell: ({ row }) => <ConfigurationCell item={row.original} />,
        },
        {
            id: 'status',
            header: 'Status',
            cell: ({ row }) => <QuillStatusIcon status={row.original.status} message={row.original.statusMessage} />,
        },
        {
            id: 'actions',
            header: 'Actions',
            meta: { align: 'right' },
            cell: ({ row }) => {
                const item = row.original

                if (item.isNative) {
                    return (
                        <Button
                            size="icon-sm"
                            aria-label="Configure source schemas"
                            tooltip="Configure source schemas"
                            nativeButton={false}
                            render={<LinkPrimitive to={item.sourceUrl} />}
                            disabledReason={restrictedReason}
                        >
                            <IconGear />
                        </Button>
                    )
                }

                if (item.isTable && item.table) {
                    const table = item.table

                    return (
                        <div className="flex justify-end gap-1">
                            <Button
                                size="icon-sm"
                                aria-label="Map columns"
                                tooltip="Map columns"
                                onClick={() => onEditTable(table)}
                                disabledReason={restrictedReason}
                            >
                                <IconPencil />
                            </Button>
                            {hasAnyMapping(table) && (
                                <Button
                                    size="icon-sm"
                                    variant="destructive-outline"
                                    aria-label="Remove all mappings"
                                    tooltip="Remove all mappings"
                                    onClick={() => onRemoveTableMapping(table)}
                                    disabledReason={restrictedReason}
                                >
                                    <IconTrash />
                                </Button>
                            )}
                        </div>
                    )
                }

                return <span>-</span>
            },
        },
    ]

    return (
        <section className="flex flex-col gap-2">
            <Heading size="sm" render={<h3 className="m-0" />}>
                Data source configuration
            </Heading>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Connect and configure data sources to enable marketing analytics. Native sources sync automatically,
                while warehouse, file, and self-managed sources need column mapping.
            </Text>

            {hasNoConfiguredSources &&
                (unconfiguredNativeSources.length > 0 ? (
                    <Item tone="warning" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                {unconfiguredNativeSources.length === 1
                                    ? `${nativeSourceDisplayLabel(unconfiguredNativeSources[0].source_type)} is connected but isn't syncing the tables marketing analytics needs.`
                                    : "Your ad integrations are connected but aren't syncing the tables marketing analytics needs."}{' '}
                                Open the source settings below and turn on the tables listed under "To sync".
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                ) : (
                    <Item tone="destructive" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                To use the Marketing analytics dashboard, you need at least one data source properly
                                configured. Add a native integration (like Google Ads or Facebook Ads) or connect a data
                                warehouse source below.
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                ))}

            <QuillPaginationControls
                hasMoreItems={hasMoreSources}
                showAll={showAll}
                onToggleShowAll={onToggleShowAll}
                totalCount={totalCount}
                itemName={ItemName.Sources}
                maxItemsToShow={MAX_ITEMS_TO_SHOW}
                additionalControls={<AddIntegrationButton />}
            />

            {loading && displayedSources.length === 0 ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-10" />
                    <Skeleton className="h-10" />
                </div>
            ) : (
                <DataTable columns={columns} data={displayedSources} getRowId={(item) => item.id} fullWidth />
            )}

            <ColumnMappingModal table={editingTable} isOpen={!!editingTable} onClose={() => onEditTable(null)} />
        </section>
    )
}
