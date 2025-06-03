import { IconCheck, IconTrash, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSelectSection, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import { MARKETING_ANALYTICS_SCHEMA } from '~/queries/schema/schema-general'
import { ExternalDataSource, PipelineNodeTab, PipelineStage } from '~/types'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { OPTIONS_FOR_IMPORTANT_CURRENCIES_ABBREVIATED, OPTIONS_FOR_OTHER_CURRENCIES_ABBREVIATED } from './utils'

export type SimpleDataWarehouseTable = {
    name: string
    source_type: ExternalDataSource['source_type']
    id: string
    source_id: string
    source_prefix: string
    columns?: { name: string; type: string }[]
    url_pattern?: string
}

interface SharedExternalDataSourceConfigurationProps {
    title: string
    description: string
    tables: SimpleDataWarehouseTable[]
    loading: boolean
    buttonRef?: React.RefObject<HTMLButtonElement>
    renderSourceIcon: (item: SimpleDataWarehouseTable) => JSX.Element
}

export function SharedExternalDataSourceConfiguration({
    title,
    description,
    tables,
    loading,
    buttonRef,
    renderSourceIcon,
}: SharedExternalDataSourceConfigurationProps): JSX.Element {
    const { sources_map } = useValues(marketingAnalyticsSettingsLogic)
    const { updateSourceMapping } = useActions(marketingAnalyticsSettingsLogic)

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

        const columnOptions: LemonSelectSection<string | null>[] = [
            {
                options: [
                    {
                        label: 'None',
                        value: null,
                    },
                ],
            },
            {
                options: compatibleColumns.map((col) => ({
                    label: `${col.name} (${col.type})`,
                    value: col.name,
                })),
            },
        ]

        if (expectedTypes.type.includes('currency')) {
            columnOptions.push(
                ...[
                    { options: OPTIONS_FOR_IMPORTANT_CURRENCIES_ABBREVIATED, title: 'Most Popular' },
                    { options: OPTIONS_FOR_OTHER_CURRENCIES_ABBREVIATED, title: 'Other currencies' },
                ]
            )
        }

        return (
            <LemonSelect
                value={currentValue || null}
                onChange={(value) => updateSourceMapping(table.id, fieldName, value)}
                options={columnOptions}
                placeholder="Select..."
                size="small"
            />
        )
    }

    const removeTableMapping = (tableId: string): void => {
        // Remove all field mappings for this table by setting each to undefined
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
        const requiredFields = Object.keys(MARKETING_ANALYTICS_SCHEMA)
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
            <h3 className="mb-2">{title}</h3>
            <p className="mb-4">{description}</p>
            <LemonTable
                rowKey={(item) => item.id}
                loading={loading}
                dataSource={tables}
                columns={[
                    {
                        key: 'source_icon',
                        title: '',
                        width: 0,
                        render: (_, item: SimpleDataWarehouseTable) => renderSourceIcon(item),
                    },
                    {
                        key: 'source',
                        title: 'Source',
                        width: 0,
                        render: (_, item: SimpleDataWarehouseTable) => {
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
                        render: (_, item: SimpleDataWarehouseTable) => item.name,
                    },
                    {
                        key: 'status',
                        title: 'Status',
                        width: 80,
                        render: (_, item: SimpleDataWarehouseTable) => {
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
                    // Required fields first
                    ...Object.keys(MARKETING_ANALYTICS_SCHEMA)
                        .filter((column) => MARKETING_ANALYTICS_SCHEMA[column].required)
                        .sort()
                        .map((column) => ({
                            key: column,
                            title: `${column.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())} (*)`,
                            render: (_: any, item: SimpleDataWarehouseTable) =>
                                renderColumnMappingDropdown(item, column),
                        })),
                    ...Object.keys(MARKETING_ANALYTICS_SCHEMA)
                        .filter((column) => !MARKETING_ANALYTICS_SCHEMA[column].required)
                        .sort()
                        .map((column) => ({
                            key: column,
                            title: `${column.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}`,
                            render: (_: any, item: SimpleDataWarehouseTable) =>
                                renderColumnMappingDropdown(item, column),
                        })),
                    {
                        key: 'actions',
                        width: 0,
                        title: (
                            <LemonButton
                                className="my-1"
                                ref={buttonRef}
                                type="primary"
                                onClick={() => {
                                    router.actions.push(urls.pipelineNodeNew(PipelineStage.Source))
                                }}
                            >
                                Add new source
                            </LemonButton>
                        ),
                        render: (_, item: SimpleDataWarehouseTable) => {
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
