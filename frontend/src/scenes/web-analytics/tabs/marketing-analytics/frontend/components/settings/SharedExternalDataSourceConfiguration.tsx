import { useActions } from 'kea'
import { useState } from 'react'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { MarketingAnalyticsColumnsSchemaNames } from '~/queries/schema/schema-general'
import { ExternalDataSchemaStatus } from '~/types'

import { useSortedPaginatedList } from '../../hooks/useSortedPaginatedList'
import { ExternalTable, MarketingSourceStatus, SourceStatus } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { MAX_ITEMS_TO_SHOW } from '../../logic/utils'
import { AddSourceDropdown } from './AddSourceDropdown'
import { ColumnMappingModal } from './ColumnMappingModal'
import { ItemName, PaginationControls } from './PaginationControls'
import { StatusIcon } from './StatusIcon'

export type SimpleDataWarehouseTable = {
    name: string
    source_type: string
    id: string
    source_map_id: string
    source_prefix: string
    columns?: { name: string; type: string }[]
    url_pattern?: string
    sourceUrl?: string
}

interface SharedExternalDataSourceConfigurationProps<T extends string> {
    title?: string
    description?: string
    tables: ExternalTable[]
    loading: boolean
    validSources: T[]
    onSourceAdd: (source: T) => void
}

export function SharedExternalDataSourceConfiguration<T extends string>({
    title,
    description,
    tables,
    loading,
    validSources,
    onSourceAdd,
}: SharedExternalDataSourceConfigurationProps<T>): JSX.Element {
    const { updateSourceMapping } = useActions(marketingAnalyticsSettingsLogic)
    const [editingTable, setEditingTable] = useState<ExternalTable | null>(null)

    const isTableFullyConfigured = (table: ExternalTable & { status?: SourceStatus }): boolean => {
        return table.status === ExternalDataSchemaStatus.Completed
    }

    const {
        displayedItems: displayedTables,
        sortedItems: tablesToUse,
        hasMoreItems: hasMoreTables,
        showAll,
        setShowAll,
    } = useSortedPaginatedList({
        items: tables,
        maxItemsToShow: MAX_ITEMS_TO_SHOW,
        getId: (table) => table.id,
        isItemConfigured: isTableFullyConfigured,
    })

    const removeTableMapping = (table: ExternalTable): void => {
        // Remove all field mappings for this table by setting each to null
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
        <SceneSection title={title} description={description}>
            <PaginationControls
                hasMoreItems={hasMoreTables}
                showAll={showAll}
                onToggleShowAll={() => setShowAll(!showAll)}
                totalCount={tablesToUse.length}
                itemName={ItemName.Tables}
                maxItemsToShow={MAX_ITEMS_TO_SHOW}
                additionalControls={<AddSourceDropdown<T> sources={validSources} onSourceAdd={onSourceAdd} />}
            />
            <LemonTable
                rowKey={(item) => item.id}
                loading={loading}
                dataSource={displayedTables}
                columns={[
                    {
                        key: 'source_icon',
                        title: '',
                        width: 0,
                        render: (
                            _,
                            item: ExternalTable & { status?: SourceStatus; statusMessage?: string }
                        ): JSX.Element => <DataWarehouseSourceIcon type={item.source_type} />,
                    },
                    {
                        key: 'source',
                        title: 'Source',
                        width: 0,
                        render: (
                            _,
                            item: ExternalTable & { status?: SourceStatus; statusMessage?: string }
                        ): JSX.Element => {
                            return item.sourceUrl ? (
                                <Link to={item.sourceUrl}>
                                    {item.source_type} {item.source_prefix}
                                </Link>
                            ) : (
                                <span>
                                    {item.source_type} {item.source_prefix}
                                </span>
                            )
                        },
                    },
                    {
                        key: 'prefix',
                        title: 'Table',
                        render: (_, item: ExternalTable & { status?: SourceStatus; statusMessage?: string }): string =>
                            item.name,
                    },
                    {
                        key: 'status',
                        title: 'Status',
                        width: 80,
                        render: (
                            _,
                            item: ExternalTable & { status?: SourceStatus; statusMessage?: string }
                        ): JSX.Element => {
                            return (
                                <StatusIcon
                                    status={item.status || MarketingSourceStatus.Error}
                                    message={item.statusMessage || 'Unknown status'}
                                />
                            )
                        },
                    },
                    {
                        key: 'actions',
                        width: 0,
                        title: 'Actions',
                        render: (
                            _,
                            item: ExternalTable & { status?: SourceStatus; statusMessage?: string }
                        ): JSX.Element => {
                            const tableHasMapping = hasAnyMapping(item)
                            return (
                                <div className="flex gap-1">
                                    <LemonButton
                                        icon={<IconPencil />}
                                        size="small"
                                        onClick={() => setEditingTable(item)}
                                        tooltip="Configure column mappings"
                                    />
                                    {tableHasMapping && (
                                        <LemonButton
                                            icon={<IconTrash />}
                                            size="small"
                                            status="danger"
                                            onClick={() => removeTableMapping(item)}
                                            tooltip="Remove all mappings for this table"
                                        />
                                    )}
                                </div>
                            )
                        },
                    },
                ]}
            />
            <ColumnMappingModal table={editingTable} isOpen={!!editingTable} onClose={() => setEditingTable(null)} />
        </SceneSection>
    )
}
