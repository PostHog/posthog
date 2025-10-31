import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGear, IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { MarketingAnalyticsColumnsSchemaNames } from '~/queries/schema/schema-general'
import { ExternalDataSchemaStatus, ExternalDataSource, ManualLinkSourceType } from '~/types'

import { useSortedPaginatedList } from '../../hooks/useSortedPaginatedList'
import {
    ExternalTable,
    MarketingSourceStatus,
    SourceStatus,
    marketingAnalyticsLogic,
} from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import {
    MAX_ITEMS_TO_SHOW,
    NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS,
    NativeMarketingSource,
    NonNativeMarketingSource,
    VALID_NATIVE_MARKETING_SOURCES,
    VALID_NON_NATIVE_MARKETING_SOURCES,
    VALID_SELF_MANAGED_MARKETING_SOURCES,
} from '../../logic/utils'
import { AddIntegrationButton } from '../MarketingAnalyticsFilters/AddIntegrationButton'
import { ColumnMappingModal } from './ColumnMappingModal'
import { ListDisplay } from './ListDisplay'
import { ItemName, PaginationControls } from './PaginationControls'
import { StatusIcon } from './StatusIcon'

type UnifiedSource = {
    id: string
    name: string
    sourceType: string
    sourceTypeLabel: 'Native' | 'Data warehouse' | 'Self-managed'
    status: SourceStatus
    statusMessage: string
    sourceUrl?: string
    // For native sources
    isNative?: boolean
    syncingTables?: string[]
    tablesToSync?: string[]
    nativeSource?: ExternalDataSource & { status?: string; statusMessage?: string }
    // For non-native/self-managed
    isTable?: boolean
    table?: ExternalTable
}

export function ExternalDataSourceConfiguration(): JSX.Element {
    const { allExternalTablesWithStatus, loading } = useValues(marketingAnalyticsLogic)
    const { updateSourceMapping } = useActions(marketingAnalyticsSettingsLogic)
    const [editingTable, setEditingTable] = useState<ExternalTable | null>(null)

    // Helper to get sync info for native sources
    const getSourceSyncInfo = (source: ExternalDataSource): { syncingTables: string[]; tablesToSync: string[] } => {
        const requiredFields =
            NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS[
                source.source_type as keyof typeof NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS
            ] || []

        if (!requiredFields.length || !source.schemas) {
            return { syncingTables: [], tablesToSync: [] }
        }

        const syncingTables = requiredFields.filter((field) => {
            const schema = source.schemas?.find((s) => s.name === field)
            return schema?.should_sync ?? false
        })

        const tablesToSync = requiredFields.filter((field) => !syncingTables.includes(field))

        return { syncingTables, tablesToSync }
    }

    // Unify all sources into a single list
    const unifiedSources: UnifiedSource[] = allExternalTablesWithStatus
        .map((item: any) => {
            // Check if this is a native source
            if (
                item.isNativeSource ||
                VALID_NATIVE_MARKETING_SOURCES.includes(item.source_type as NativeMarketingSource)
            ) {
                const { syncingTables, tablesToSync } = getSourceSyncInfo(item as ExternalDataSource)
                return {
                    id: `native-${item.id}`,
                    name: item.prefix || item.source_type,
                    sourceType: item.source_type,
                    sourceTypeLabel: 'Native' as const,
                    status: item.status || MarketingSourceStatus.Error,
                    statusMessage: item.statusMessage || 'Unknown status',
                    sourceUrl: urls.dataWarehouseSource(`managed-${item.id}`),
                    isNative: true,
                    syncingTables,
                    tablesToSync,
                    nativeSource: item as ExternalDataSource,
                }
            }

            // Check if this is a BigQuery/warehouse source
            if (VALID_NON_NATIVE_MARKETING_SOURCES.includes(item.source_type as NonNativeMarketingSource)) {
                return {
                    id: `table-${item.id}`,
                    name: item.name,
                    sourceType: `${item.source_type} ${item.source_prefix}`,
                    sourceTypeLabel: 'Data warehouse' as const,
                    status: item.status || MarketingSourceStatus.Error,
                    statusMessage: item.statusMessage || 'Unknown status',
                    sourceUrl: item.sourceUrl,
                    isTable: true,
                    table: item,
                }
            }

            // Check if this is a self-managed source
            if (VALID_SELF_MANAGED_MARKETING_SOURCES.includes(item.source_type as ManualLinkSourceType)) {
                return {
                    id: `table-${item.id}`,
                    name: item.name,
                    sourceType: `${item.source_type} ${item.source_prefix}`,
                    sourceTypeLabel: 'Self-managed' as const,
                    status: item.status || MarketingSourceStatus.Error,
                    statusMessage: item.statusMessage || 'Unknown status',
                    sourceUrl: item.sourceUrl,
                    isTable: true,
                    table: item,
                }
            }

            // Fallback for unknown types
            return null
        })
        .filter(Boolean) as UnifiedSource[]

    const isSourceFullyConfigured = (source: UnifiedSource): boolean => {
        return source.status === ExternalDataSchemaStatus.Completed || source.status === MarketingSourceStatus.Success
    }

    const {
        displayedItems: displayedSources,
        sortedItems: sourcesToUse,
        hasMoreItems: hasMoreSources,
        showAll,
        setShowAll,
    } = useSortedPaginatedList({
        items: unifiedSources,
        maxItemsToShow: MAX_ITEMS_TO_SHOW,
        getId: (source) => source.id,
        isItemConfigured: isSourceFullyConfigured,
    })

    const removeTableMapping = (table: ExternalTable): void => {
        const sourceMapping = table.source_map
        if (sourceMapping) {
            Object.keys(sourceMapping).forEach((fieldName: string) => {
                updateSourceMapping(table.source_map_id, fieldName as MarketingAnalyticsColumnsSchemaNames, null)
            })
        }
    }

    const hasAnyMapping = (table: ExternalTable): boolean => {
        const sourceMapping = table.source_map
        return !!(sourceMapping && Object.keys(sourceMapping).length > 0)
    }

    return (
        <SceneSection
            title="Data source configuration"
            description="Connect and configure data sources to enable marketing analytics. Native sources sync automatically, while warehouse and self-managed sources need column mapping."
        >
            <PaginationControls
                hasMoreItems={hasMoreSources}
                showAll={showAll}
                onToggleShowAll={() => setShowAll(!showAll)}
                totalCount={sourcesToUse.length}
                itemName={ItemName.Sources}
                maxItemsToShow={MAX_ITEMS_TO_SHOW}
                additionalControls={<AddIntegrationButton />}
            />
            <LemonTable
                rowKey={(item) => item.id}
                loading={loading}
                dataSource={displayedSources}
                columns={[
                    {
                        key: 'icon',
                        title: '',
                        width: 0,
                        render: (_, item: UnifiedSource): JSX.Element => (
                            <DataWarehouseSourceIcon
                                type={item.nativeSource?.source_type || item.table?.source_type || ''}
                            />
                        ),
                    },
                    {
                        key: 'name',
                        title: 'Name',
                        render: (_, item: UnifiedSource): JSX.Element => {
                            return item.sourceUrl ? (
                                <Link to={item.sourceUrl}>{item.name}</Link>
                            ) : (
                                <span>{item.name}</span>
                            )
                        },
                    },
                    {
                        key: 'type',
                        title: 'Type',
                        width: 150,
                        render: (_, item: UnifiedSource): JSX.Element => (
                            <LemonTag
                                type={
                                    item.sourceTypeLabel === 'Native'
                                        ? 'success'
                                        : item.sourceTypeLabel === 'Data warehouse'
                                          ? 'default'
                                          : 'primary'
                                }
                            >
                                {item.sourceTypeLabel}
                            </LemonTag>
                        ),
                    },
                    {
                        key: 'source',
                        title: 'Source',
                        width: 150,
                        render: (_, item: UnifiedSource): string => item.sourceType,
                    },
                    {
                        key: 'config',
                        title: 'Configuration',
                        width: 200,
                        render: (_, item: UnifiedSource): JSX.Element => {
                            if (item.isNative && item.syncingTables && item.tablesToSync) {
                                return (
                                    <div className="space-y-1">
                                        {item.syncingTables.length > 0 && (
                                            <div className="text-xs">
                                                <span className="text-muted">Syncing: </span>
                                                <ListDisplay list={item.syncingTables} />
                                            </div>
                                        )}
                                        {item.tablesToSync.length > 0 && (
                                            <div className="text-xs">
                                                <span className="text-muted">To sync: </span>
                                                <ListDisplay list={item.tablesToSync} />
                                            </div>
                                        )}
                                        {item.syncingTables.length === 0 && item.tablesToSync.length === 0 && (
                                            <span className="text-muted text-xs">No tables required</span>
                                        )}
                                    </div>
                                )
                            }
                            if (item.isTable && item.table) {
                                const mappedFields = item.table.source_map
                                    ? Object.keys(item.table.source_map).length
                                    : 0
                                return (
                                    <span className="text-xs">
                                        {mappedFields > 0 ? (
                                            <span>{mappedFields} columns mapped</span>
                                        ) : (
                                            <span className="text-muted">No columns mapped</span>
                                        )}
                                    </span>
                                )
                            }
                            return <span className="text-muted text-xs">-</span>
                        },
                    },
                    {
                        key: 'status',
                        title: 'Status',
                        width: 80,
                        render: (_, item: UnifiedSource): JSX.Element => (
                            <StatusIcon status={item.status} message={item.statusMessage} />
                        ),
                    },
                    {
                        key: 'actions',
                        title: 'Actions',
                        width: 80,
                        render: (_, item: UnifiedSource): JSX.Element => {
                            if (item.isNative) {
                                return (
                                    <LemonButton
                                        icon={<IconGear />}
                                        size="small"
                                        to={item.sourceUrl}
                                        tooltip="Configure source schemas"
                                    />
                                )
                            }
                            if (item.isTable && item.table) {
                                const tableHasMapping = hasAnyMapping(item.table)
                                return (
                                    <div className="flex gap-1">
                                        <LemonButton
                                            icon={<IconPencil />}
                                            size="small"
                                            onClick={() => setEditingTable(item.table!)}
                                            tooltip="Map columns"
                                        />
                                        {tableHasMapping && (
                                            <LemonButton
                                                icon={<IconTrash />}
                                                size="small"
                                                status="danger"
                                                onClick={() => removeTableMapping(item.table!)}
                                                tooltip="Remove all mappings"
                                            />
                                        )}
                                    </div>
                                )
                            }
                            return <span>-</span>
                        },
                    },
                ]}
            />
            <ColumnMappingModal table={editingTable} isOpen={!!editingTable} onClose={() => setEditingTable(null)} />
        </SceneSection>
    )
}
