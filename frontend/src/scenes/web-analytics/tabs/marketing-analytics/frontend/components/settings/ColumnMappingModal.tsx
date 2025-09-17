import { useActions, useValues } from 'kea'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSelect, LemonSelectSection } from '@posthog/lemon-ui'

import { OPTIONS_FOR_IMPORTANT_CURRENCIES, OPTIONS_FOR_OTHER_CURRENCIES } from 'lib/components/BaseCurrency/utils'

import { MARKETING_ANALYTICS_SCHEMA, MarketingAnalyticsColumnsSchemaNames } from '~/queries/schema/schema-general'

import { ExternalTable } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'

interface ColumnMappingModalProps {
    table: ExternalTable | null
    isOpen: boolean
    onClose: () => void
}

enum FieldStatus {
    Complete = 'complete',
    Empty = 'empty',
    Partial = 'partial',
}

export function ColumnMappingModal({ table, isOpen, onClose }: ColumnMappingModalProps): JSX.Element {
    const { updateSourceMapping } = useActions(marketingAnalyticsSettingsLogic)
    const { sources_map } = useValues(marketingAnalyticsSettingsLogic)

    const requiredFields = Object.values(MarketingAnalyticsColumnsSchemaNames).filter(
        (field) => MARKETING_ANALYTICS_SCHEMA[field].required
    )
    const optionalFields = Object.values(MarketingAnalyticsColumnsSchemaNames).filter(
        (field) => !MARKETING_ANALYTICS_SCHEMA[field].required
    )

    if (!table) {
        return <></>
    }

    // Get the current mapping from the sources_map to ensure we have the latest data
    const currentSourceMap = sources_map[table.source_map_id] ?? {}

    const isColumnTypeCompatible = (
        columnType: string,
        schemaField: { required: boolean; type: string[] }
    ): boolean => {
        return schemaField.type.includes(columnType)
    }

    const renderColumnMappingDropdown = (fieldName: MarketingAnalyticsColumnsSchemaNames): JSX.Element => {
        const currentValue = currentSourceMap[fieldName] ?? null
        const expectedTypes = MARKETING_ANALYTICS_SCHEMA[fieldName]
        const compatibleColumns = table.columns?.filter((col) => isColumnTypeCompatible(col.type, expectedTypes)) || []

        let columnOptions: LemonSelectSection<string | null>[]
        if (fieldName === MarketingAnalyticsColumnsSchemaNames.Currency) {
            columnOptions = [
                { options: [{ label: 'None', value: null }] },
                { options: OPTIONS_FOR_IMPORTANT_CURRENCIES, title: 'Most Popular' },
                { options: OPTIONS_FOR_OTHER_CURRENCIES, title: 'Other currencies' },
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
                value={currentValue}
                onChange={(value) => updateSourceMapping(table.source_map_id, fieldName, value)}
                options={columnOptions}
                placeholder="Select..."
                fullWidth
                renderButtonContent={(activeLeaf) => {
                    // For non-currency fields, show just the column name without type when selected
                    if (fieldName !== MarketingAnalyticsColumnsSchemaNames.Currency && activeLeaf?.value) {
                        return activeLeaf.value
                    }
                    // For currency or when no selection, use default behavior
                    return activeLeaf?.label || ''
                }}
            />
        )
    }

    const getFieldStatus = (fieldName: MarketingAnalyticsColumnsSchemaNames): FieldStatus => {
        const mapping = currentSourceMap[fieldName]
        if (!mapping || mapping.trim() === '') {
            return FieldStatus.Empty
        }
        return FieldStatus.Complete
    }

    const getStatusIcon = (status: FieldStatus): JSX.Element => {
        switch (status) {
            case FieldStatus.Complete:
                return <IconCheck className="text-success text-sm" />
            case FieldStatus.Partial:
                return <IconWarning className="text-warning text-sm" />
            case FieldStatus.Empty:
                return <IconX className="text-muted text-sm" />
        }
    }

    const requiredFieldsConfigured = requiredFields.filter((field) => {
        const mapping = currentSourceMap[field]
        return mapping && mapping.trim() !== ''
    }).length

    const clearAllMappings = (): void => {
        Object.keys(currentSourceMap).forEach((fieldName) => {
            updateSourceMapping(table.source_map_id, fieldName as MarketingAnalyticsColumnsSchemaNames, null)
        })
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={`Configure ${table.name} Mapping`}
            width={600}
            footer={
                <div className="flex justify-between items-center w-full">
                    <span className="text-sm text-muted">
                        {requiredFieldsConfigured}/{requiredFields.length} required fields configured
                    </span>
                    <div className="flex items-center gap-2">
                        <LemonButton onClick={clearAllMappings} tooltip="Clear all mappings for this table">
                            Clear
                        </LemonButton>
                        <LemonButton type="primary" onClick={onClose}>
                            Done
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="space-y-6">
                <div>
                    <h4 className="font-semibold mb-3">Required Fields</h4>
                    <div className="space-y-4">
                        {requiredFields.sort().map((fieldName) => (
                            <div key={fieldName} className="flex items-center gap-3">
                                <div className="w-6 flex justify-center">
                                    {getStatusIcon(getFieldStatus(fieldName))}
                                </div>
                                <div className="w-40">
                                    <span className="font-medium">
                                        {fieldName.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
                                    </span>
                                </div>
                                <div className="flex-1">{renderColumnMappingDropdown(fieldName)}</div>
                            </div>
                        ))}
                    </div>
                </div>

                {optionalFields.length > 0 && (
                    <div>
                        <h4 className="font-semibold mb-3">Optional Fields</h4>
                        <div className="space-y-4">
                            {optionalFields.sort().map((fieldName) => (
                                <div key={fieldName} className="flex items-center gap-3">
                                    <div className="w-6 flex justify-center">
                                        {getStatusIcon(getFieldStatus(fieldName))}
                                    </div>
                                    <div className="w-40">
                                        <span className="font-medium">
                                            {fieldName.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
                                        </span>
                                    </div>
                                    <div className="flex-1">{renderColumnMappingDropdown(fieldName)}</div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
