import { IconCheck, IconPlus, IconTrash, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonSelect, LemonSelectSection, Link } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import {
    OPTIONS_FOR_IMPORTANT_CURRENCIES_ABBREVIATED,
    OPTIONS_FOR_OTHER_CURRENCIES_ABBREVIATED,
} from 'lib/components/BaseCurrency/utils'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { ExternalDataSource, ManualLinkSourceType } from '~/types'

import { MARKETING_ANALYTICS_SCHEMA } from '../../../utils'
import { ExternalTable } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'

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

interface SharedExternalDataSourceConfigurationProps {
    title: string
    description: string
    tables: ExternalTable[]
    loading: boolean
    validSources: ExternalDataSource['source_type'][] | ManualLinkSourceType[]
    onSourceAdd: (source: any) => void // Need any because self-managed and non-native sources have different types
}

export function SharedExternalDataSourceConfiguration({
    title,
    description,
    tables,
    loading,
    validSources,
    onSourceAdd,
}: SharedExternalDataSourceConfigurationProps): JSX.Element {
    const { updateSourceMapping } = useActions(marketingAnalyticsSettingsLogic)
    const requiredFields = Object.keys(MARKETING_ANALYTICS_SCHEMA).filter(
        (field) => MARKETING_ANALYTICS_SCHEMA[field].required
    )

    const isColumnTypeCompatible = (
        columnType: string,
        schemaField: { required: boolean; type: string[] }
    ): boolean => {
        return schemaField.type.includes(columnType)
    }

    const renderColumnMappingDropdown = (
        table: ExternalTable,
        fieldName: keyof typeof MARKETING_ANALYTICS_SCHEMA
    ): JSX.Element => {
        const currentValue = table.source_map?.[fieldName]
        const expectedTypes = MARKETING_ANALYTICS_SCHEMA[fieldName]
        const compatibleColumns = table.columns?.filter((col) => isColumnTypeCompatible(col.type, expectedTypes)) || []

        let columnOptions: LemonSelectSection<string | null>[]
        if (fieldName === 'currency') {
            columnOptions = [
                { options: [{ label: 'None', value: null }] },
                { options: OPTIONS_FOR_IMPORTANT_CURRENCIES_ABBREVIATED, title: 'Most Popular' },
                { options: OPTIONS_FOR_OTHER_CURRENCIES_ABBREVIATED, title: 'Other currencies' },
            ]
        } else {
            columnOptions = [
                { options: [{ label: 'None', value: null }] },
                {
                    options: compatibleColumns.map((col) => ({
                        label: `${col.name} (${col.type})`,
                        value: col.name,
                    })),
                },
            ]
        }

        return (
            <LemonSelect
                value={currentValue || null}
                onChange={(value) => updateSourceMapping(table.source_map_id, fieldName, value)}
                options={columnOptions}
                placeholder="Select..."
                size="small"
            />
        )
    }

    const removeTableMapping = (table: ExternalTable): void => {
        // Remove all field mappings for this table by setting each to null
        const sourceMapping = table.source_map

        if (sourceMapping) {
            Object.keys(sourceMapping).forEach((fieldName) => {
                updateSourceMapping(table.source_map_id, fieldName, null)
            })
        }
    }

    const hasAnyMapping = (table: ExternalTable): boolean => {
        const sourceMapping = table.source_map
        return sourceMapping ? Object.keys(sourceMapping).length > 0 : false
    }

    const isTableFullyConfigured = (table: ExternalTable): boolean => {
        const sourceMapping = table.source_map
        if (!sourceMapping) {
            return false
        }

        return requiredFields.every((fieldName: string) => {
            const mapping = sourceMapping[fieldName]
            return mapping && mapping.trim() !== ''
        })
    }

    const getTableStatus = (table: ExternalTable): { isConfigured: boolean; message: string } => {
        const sourceMapping = table.source_map
        if (!sourceMapping || Object.keys(sourceMapping).length === 0) {
            return { isConfigured: false, message: 'No fields mapped' }
        }

        if (isTableFullyConfigured(table)) {
            return { isConfigured: true, message: 'Ready to use! All fields mapped correctly.' }
        }

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
                        render: (_, item: ExternalTable) => <DataWarehouseSourceIcon type={item.source_type} />,
                    },
                    {
                        key: 'source',
                        title: 'Source',
                        width: 0,
                        render: (_, item: ExternalTable) => {
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
                        render: (_, item: ExternalTable) => item.name,
                    },
                    {
                        key: 'status',
                        title: 'Status',
                        width: 80,
                        render: (_, item: ExternalTable) => {
                            const { isConfigured, message } = getTableStatus(item)
                            const sourceMapping = item.source_map
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
                    ...requiredFields.sort().map((column) => ({
                        key: column,
                        title: `${column.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())} (*)`,
                        render: (_: any, item: ExternalTable) => renderColumnMappingDropdown(item, column),
                    })),
                    ...Object.keys(MARKETING_ANALYTICS_SCHEMA)
                        .filter((column) => !MARKETING_ANALYTICS_SCHEMA[column].required)
                        .sort()
                        .map((column) => ({
                            key: column,
                            title: `${column.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}`,
                            render: (_: any, item: ExternalTable) => renderColumnMappingDropdown(item, column),
                        })),
                    {
                        key: 'actions',
                        width: 0,
                        title: (
                            <LemonDropdown
                                className="my-1"
                                overlay={
                                    <div className="p-1">
                                        {validSources.map((source) => (
                                            <LemonButton
                                                key={source}
                                                onClick={() => onSourceAdd(source)}
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
                        render: (_, item: ExternalTable) => {
                            const tableHasMapping = hasAnyMapping(item)
                            return tableHasMapping ? (
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="small"
                                    status="danger"
                                    onClick={() => removeTableMapping(item)}
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
