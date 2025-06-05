import { IconCheck, IconPlus, IconTrash, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonSelect, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { ExternalDataSource, PipelineNodeTab, PipelineStage } from '~/types'

import { MARKETING_ANALYTICS_SCHEMA } from '../../../utils'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'

const VALID_MARKETING_SOURCES: ExternalDataSource['source_type'][] = ['BigQuery']

type SimpleDataWarehouseTable = {
    name: string
    source_type: ExternalDataSource['source_type']
    id: string
    source_id: string
    source_prefix: string
    columns?: { name: string; type: string }[]
}

// This is to map tables that are not natively integrated with PostHog.
// It's a workaround to allow users to map columns to the correct fields in the Marketing Analytics product.
// An example of native integration is the Google Ads integration.
export function NonNativeExternalDataSourceConfiguration(): JSX.Element {
    const { dataWarehouseSources, sources_map } = useValues(marketingAnalyticsSettingsLogic)
    const { updateSourceMapping } = useActions(marketingAnalyticsSettingsLogic)
    const marketingSources =
        dataWarehouseSources?.results.filter((source) => VALID_MARKETING_SOURCES.includes(source.source_type)) ?? []

    const tables = marketingSources
        .map((source) =>
            source.schemas.map((schema) => ({
                ...schema,
                source_type: source.source_type,
                source_id: source.id,
                source_prefix: source.prefix,
                columns: schema.table?.columns || [],
            }))
        )
        .flat()

    const isColumnTypeCompatible = (
        columnType: string,
        schemaField: { required: boolean; type: string[] }
    ): boolean => {
        return schemaField.type.includes(columnType)
    }

    const renderColumnMappingDropdown = (
        table: SimpleDataWarehouseTable,
        fieldName: keyof typeof MARKETING_ANALYTICS_SCHEMA
    ): JSX.Element => {
        const sourceMapping = sources_map?.[table.id]
        const currentValue = sourceMapping?.[fieldName]
        const expectedTypes = MARKETING_ANALYTICS_SCHEMA[fieldName]
        const compatibleColumns = table.columns?.filter((col) => isColumnTypeCompatible(col.type, expectedTypes)) || []

        const columnOptions = [
            { label: 'None', value: null as string | null },
            ...compatibleColumns.map((col) => ({
                label: `${col.name} (${col.type})`,
                value: col.name as string | null,
            })),
        ]

        return (
            <LemonSelect
                value={currentValue || null}
                onChange={(value) => updateSourceMapping(table.id, fieldName, value)}
                options={columnOptions}
                placeholder="Select column..."
                size="small"
            />
        )
    }

    const removeTableMapping = (tableId: string): void => {
        // Remove all field mappings for this table by setting each to null
        const sourceMapping = sources_map?.[tableId]

        if (sourceMapping) {
            Object.keys(sourceMapping).forEach((fieldName) => {
                updateSourceMapping(tableId, fieldName, null)
            })
        }
    }

    const hasAnyMapping = (tableId: string): boolean => {
        const sourceMapping = sources_map?.[tableId]
        return sourceMapping && Object.keys(sourceMapping).length > 0
    }

    const isTableFullyConfigured = (tableId: string): boolean => {
        const sourceMapping = sources_map?.[tableId]
        if (!sourceMapping) {
            return false
        }

        // Check if all required fields from the schema are mapped
        const requiredFields = Object.keys(MARKETING_ANALYTICS_SCHEMA).filter(
            (field) => MARKETING_ANALYTICS_SCHEMA[field].required
        )
        return requiredFields.every((fieldName: string) => {
            const mapping = sourceMapping[fieldName]
            return mapping && mapping.trim() !== ''
        })
    }

    const getTableStatus = (tableId: string): { isConfigured: boolean; message: string } => {
        const sourceMapping = sources_map?.[tableId]
        if (!sourceMapping || Object.keys(sourceMapping).length === 0) {
            return { isConfigured: false, message: 'No fields mapped' }
        }

        if (isTableFullyConfigured(tableId)) {
            return { isConfigured: true, message: 'Ready to use! All fields mapped correctly.' }
        }
        const requiredFields = Object.keys(MARKETING_ANALYTICS_SCHEMA).filter(
            (fieldName) => MARKETING_ANALYTICS_SCHEMA[fieldName].required
        )
        const mappedFields = requiredFields.filter((fieldName) => {
            const mapping = sourceMapping[fieldName]
            return mapping && mapping.trim() !== ''
        })

        const missingCount = requiredFields.length - mappedFields.length
        return {
            isConfigured: false,
            message: `${missingCount} field${missingCount > 1 ? 's' : ''} still need mapping`,
        }
    }

    return (
        <div>
            <h3 className="mb-2">Non Native Data Warehouse Sources Configuration</h3>
            <p className="mb-4">
                PostHog can display marketing data in our Marketing Analytics product from the following data warehouse
                sources.
            </p>
            <LemonTable
                rowKey={(item) => item.id}
                loading={dataWarehouseSources === null}
                dataSource={tables}
                columns={[
                    {
                        key: 'source_icon',
                        title: '',
                        width: 0,
                        render: (_, item: any) => {
                            return <DataWarehouseSourceIcon type={item.source_type} />
                        },
                    },
                    {
                        key: 'source',
                        title: 'Source',
                        width: 0,
                        render: (_, item: any) => {
                            return (
                                <Link
                                    to={urls.pipelineNode(
                                        PipelineStage.Source,
                                        `managed-${item.source_id}`,
                                        PipelineNodeTab.Schemas
                                    )}
                                >
                                    {item.source_type} {item.source_prefix}
                                </Link>
                            )
                        },
                    },
                    {
                        key: 'prefix',
                        title: 'Table',
                        render: (_, item: any) => item.name,
                    },
                    {
                        key: 'status',
                        title: 'Status',
                        width: 80,
                        render: (_, item: any) => {
                            const { isConfigured, message } = getTableStatus(item.id)
                            const sourceMapping = sources_map?.[item.id]
                            const hasAnyMapping = sourceMapping && Object.keys(sourceMapping).length > 0

                            if (isConfigured) {
                                return (
                                    <Tooltip title={message}>
                                        <div className="flex justify-center">
                                            <IconCheck className="text-success text-lg" />
                                        </div>
                                    </Tooltip>
                                )
                            } else if (hasAnyMapping) {
                                return (
                                    <Tooltip title={message}>
                                        <div className="flex justify-center">
                                            <IconWarning className="text-warning text-lg" />
                                        </div>
                                    </Tooltip>
                                )
                            }
                            return (
                                <Tooltip title={message}>
                                    <div className="flex justify-center">
                                        <IconX className="text-muted text-lg" />
                                    </div>
                                </Tooltip>
                            )
                        },
                    },
                    ...Object.keys(MARKETING_ANALYTICS_SCHEMA).map((column) => ({
                        key: column,
                        title: `${column.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}${
                            MARKETING_ANALYTICS_SCHEMA[column].required ? ' (*)' : ''
                        }`,
                        render: (_: any, item: any) => renderColumnMappingDropdown(item, column),
                    })),
                    {
                        key: 'actions',
                        width: 0,
                        title: (
                            <LemonDropdown
                                className="my-1"
                                overlay={
                                    <div className="p-1">
                                        {VALID_MARKETING_SOURCES.map((source) => (
                                            <LemonButton
                                                key={source}
                                                onClick={() => {
                                                    router.actions.push(
                                                        urls.pipelineNodeNew(PipelineStage.Source, { source })
                                                    )
                                                }}
                                                fullWidth
                                                size="small"
                                            >
                                                <div className="flex items-center gap-2">
                                                    <DataWarehouseSourceIcon type={source} />
                                                    {source}
                                                    <IconPlus className="text-muted" />
                                                </div>
                                            </LemonButton>
                                        ))}
                                    </div>
                                }
                            >
                                <LemonButton type="primary" size="small">
                                    Add new source
                                </LemonButton>
                            </LemonDropdown>
                        ),
                        render: (_, item: any) => {
                            const tableHasMapping = hasAnyMapping(item.id)
                            return tableHasMapping ? (
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="small"
                                    status="danger"
                                    onClick={() => removeTableMapping(item.id)}
                                    tooltip="Remove all mappings for this table"
                                />
                            ) : null
                        },
                    },
                ]}
            />
        </div>
    )
}
