import { useActions } from 'kea'
import { useState } from 'react'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { MARKETING_ANALYTICS_SCHEMA, MarketingAnalyticsColumnsSchemaNames } from '~/queries/schema/schema-general'

import { useSortedPaginatedList } from '../../hooks/useSortedPaginatedList'
import { ExternalTable } from '../../logic/marketingAnalyticsLogic'
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
    const requiredFields = Object.values(MarketingAnalyticsColumnsSchemaNames).filter(
        (field) => MARKETING_ANALYTICS_SCHEMA[field].required
    )

    const isFieldMapped = (table: ExternalTable, fieldName: MarketingAnalyticsColumnsSchemaNames): boolean => {
        const sourceMapping = table.source_map
        if (!sourceMapping) {
            return false
        }
        const mapping = sourceMapping[fieldName]
        return !!(mapping && mapping.trim() !== '')
    }

    const getTableMappingInfo = (
        table: ExternalTable
    ): { mappedFields: string[]; unmappedFields: string[]; totalRequired: number; mappedCount: number } => {
        const sourceMapping = table.source_map
        if (!sourceMapping) {
            return {
                mappedFields: [],
                unmappedFields: requiredFields,
                totalRequired: requiredFields.length,
                mappedCount: 0,
            }
        }

        const mappedFields = requiredFields.filter((fieldName) => isFieldMapped(table, fieldName))
        const unmappedFields = requiredFields.filter((fieldName) => !isFieldMapped(table, fieldName))

        return {
            mappedFields,
            unmappedFields,
            totalRequired: requiredFields.length,
            mappedCount: mappedFields.length,
        }
    }

    const isTableFullyConfigured = (table: ExternalTable): boolean => {
        const { mappedCount, totalRequired } = getTableMappingInfo(table)
        return mappedCount === totalRequired && totalRequired > 0
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

    const getTableStatus = (table: ExternalTable): { isConfigured: boolean; message: string } => {
        if (!hasAnyMapping(table)) {
            return { isConfigured: false, message: 'No fields mapped' }
        }

        const { mappedCount, totalRequired } = getTableMappingInfo(table)

        if (mappedCount === totalRequired) {
            return { isConfigured: true, message: 'Ready to use! All fields mapped correctly.' }
        }

        const missingCount = totalRequired - mappedCount
        return {
            isConfigured: false,
            message: `${missingCount} field${missingCount > 1 ? 's' : ''} still need mapping`,
        }
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
                        render: (_, item: ExternalTable): JSX.Element => (
                            <DataWarehouseSourceIcon type={item.source_type} />
                        ),
                    },
                    {
                        key: 'source',
                        title: 'Source',
                        width: 0,
                        render: (_, item: ExternalTable): JSX.Element => {
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
                        render: (_, item: ExternalTable): string => item.name,
                    },
                    {
                        key: 'status',
                        title: 'Status',
                        width: 80,
                        render: (_, item: ExternalTable): JSX.Element => {
                            const { isConfigured, message } = getTableStatus(item)

                            if (isConfigured) {
                                return <StatusIcon status="success" message={message} />
                            } else if (hasAnyMapping(item)) {
                                return <StatusIcon status="warning" message={message} />
                            }
                            return <StatusIcon status="error" message={message} />
                        },
                    },
                    {
                        key: 'actions',
                        width: 0,
                        title: 'Actions',
                        render: (_, item: ExternalTable): JSX.Element => {
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
