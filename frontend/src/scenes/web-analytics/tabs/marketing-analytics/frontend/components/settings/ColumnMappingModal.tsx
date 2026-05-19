import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { LemonInputSelect, LemonInputSelectOption } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { CURRENCY_SYMBOL_TO_NAME_MAP, IMPORTANT_CURRENCIES, OTHER_CURRENCIES } from 'lib/utils/geography/currency'

import {
    MARKETING_ANALYTICS_SCHEMA,
    MARKETING_INTEGRATION_CONFIGS,
    MarketingAnalyticsColumnsSchemaNames,
    MarketingAnalyticsConstants,
    NativeMarketingSource,
    SourceMap,
    VALID_NATIVE_MARKETING_SOURCES,
} from '~/queries/schema/schema-general'
import type { MarketingAnalyticsSchemaFieldTypes } from '~/queries/schema/schema-general'

import { ExternalTable } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'

interface ColumnMappingModalProps {
    table: ExternalTable | null
    isOpen: boolean
    onClose: () => void
}

const PREDEFINED_SOURCE_CONSTANTS: LemonInputSelectOption[] = VALID_NATIVE_MARKETING_SOURCES.map(
    (source: NativeMarketingSource) => ({
        key: `${MarketingAnalyticsConstants.ConstantValuePrefix}${MARKETING_INTEGRATION_CONFIGS[source].primarySource}`,
        label: `${MARKETING_INTEGRATION_CONFIGS[source].primarySource} (constant)`,
    })
)

enum FieldStatus {
    Complete = 'complete',
    Empty = 'empty',
    Partial = 'partial',
}

interface ColumnMappingComboboxProps {
    fieldName: MarketingAnalyticsColumnsSchemaNames
    currentValue: string | null
    tableColumns: { name: string; type: string }[]
    onChange: (value: string | null) => void
}

const FIELDS_WITH_CONSTANT_SUPPORT = new Set([
    MarketingAnalyticsColumnsSchemaNames.Source,
    MarketingAnalyticsColumnsSchemaNames.Currency,
])

function ColumnMappingCombobox({
    fieldName,
    currentValue,
    tableColumns,
    onChange,
}: ColumnMappingComboboxProps): JSX.Element {
    const options = useMemo(() => buildColumnOptions(fieldName, tableColumns), [fieldName, tableColumns])

    const columnNames = useMemo(() => new Set(tableColumns.map((c) => c.name)), [tableColumns])

    const handleChange = (values: string[]): void => {
        let newValue = values.length > 0 ? values[values.length - 1] : null
        // Auto-prefix custom values with const: for source/currency fields
        // if the value isn't a known column and doesn't already have the prefix
        if (
            newValue &&
            FIELDS_WITH_CONSTANT_SUPPORT.has(fieldName) &&
            !newValue.startsWith(MarketingAnalyticsConstants.ConstantValuePrefix) &&
            !columnNames.has(newValue)
        ) {
            newValue = `${MarketingAnalyticsConstants.ConstantValuePrefix}${newValue}`
        }
        onChange(newValue)
    }

    return (
        <LemonInputSelect
            value={currentValue ? [currentValue] : []}
            onChange={handleChange}
            options={options}
            placeholder="Select or type..."
            mode="single"
            allowCustomValues
            fullWidth
        />
    )
}

function buildColumnOptions(
    fieldName: MarketingAnalyticsColumnsSchemaNames,
    tableColumns: { name: string; type: string }[]
): LemonInputSelectOption[] {
    const expectedTypes = MARKETING_ANALYTICS_SCHEMA[fieldName]

    if (fieldName === MarketingAnalyticsColumnsSchemaNames.Currency) {
        const currencyOptions: LemonInputSelectOption[] = []

        for (const col of tableColumns) {
            currencyOptions.push({
                key: col.name,
                label: `${col.name} (${col.type})`,
            })
        }

        // Add currency codes as constant values
        for (const code of IMPORTANT_CURRENCIES) {
            currencyOptions.push({
                key: `${MarketingAnalyticsConstants.ConstantValuePrefix}${code}`,
                label: `${code} - ${CURRENCY_SYMBOL_TO_NAME_MAP[code]} (constant)`,
            })
        }
        for (const code of OTHER_CURRENCIES) {
            currencyOptions.push({
                key: `${MarketingAnalyticsConstants.ConstantValuePrefix}${code}`,
                label: `${code} - ${CURRENCY_SYMBOL_TO_NAME_MAP[code]} (constant)`,
            })
        }

        return currencyOptions
    }

    if (fieldName === MarketingAnalyticsColumnsSchemaNames.Source) {
        const sourceOptions: LemonInputSelectOption[] = []

        // Type-compatible columns first
        const compatible = tableColumns.filter((col) =>
            expectedTypes.type.includes(col.type as MarketingAnalyticsSchemaFieldTypes)
        )
        const incompatible = tableColumns.filter(
            (col) => !expectedTypes.type.includes(col.type as MarketingAnalyticsSchemaFieldTypes)
        )

        for (const col of compatible) {
            sourceOptions.push({
                key: col.name,
                label: `${col.name} (${col.type})`,
            })
        }

        for (const col of incompatible) {
            sourceOptions.push({
                key: col.name,
                label: `${col.name} (${col.type})`,
            })
        }

        // Add predefined source constants
        sourceOptions.push(...PREDEFINED_SOURCE_CONSTANTS)

        return sourceOptions
    }

    const options: LemonInputSelectOption[] = []

    // Type-compatible columns first
    const compatible = tableColumns.filter((col) =>
        expectedTypes.type.includes(col.type as MarketingAnalyticsSchemaFieldTypes)
    )
    const incompatible = tableColumns.filter(
        (col) => !expectedTypes.type.includes(col.type as MarketingAnalyticsSchemaFieldTypes)
    )

    for (const col of compatible) {
        options.push({
            key: col.name,
            label: `${col.name} (${col.type})`,
        })
    }

    // Other columns shown after, so the user can still pick them
    for (const col of incompatible) {
        options.push({
            key: col.name,
            label: `${col.name} (${col.type})`,
        })
    }

    return options
}

export function ColumnMappingModal({ table, isOpen, onClose }: ColumnMappingModalProps): JSX.Element {
    const { updateSourceMapping, testMapping } = useActions(marketingAnalyticsSettingsLogic)
    const { sources_map, testMappingResults } = useValues(marketingAnalyticsSettingsLogic)

    const requiredFields = Object.values(MarketingAnalyticsColumnsSchemaNames).filter(
        (field) => MARKETING_ANALYTICS_SCHEMA[field].required
    )
    const optionalFields = Object.values(MarketingAnalyticsColumnsSchemaNames).filter(
        (field) => !MARKETING_ANALYTICS_SCHEMA[field].required
    )

    if (!table) {
        return <></>
    }

    const currentSourceMap = sources_map[table.source_map_id] ?? {}
    const testResult = testMappingResults[table.id]

    const renderColumnMappingCombobox = (fieldName: MarketingAnalyticsColumnsSchemaNames): JSX.Element => {
        const currentValue = currentSourceMap[fieldName] ?? null
        return (
            <ColumnMappingCombobox
                fieldName={fieldName}
                currentValue={currentValue}
                tableColumns={table.columns || []}
                onChange={(value) => updateSourceMapping(table.source_map_id, fieldName, value)}
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

    const handleTestMapping = (): void => {
        testMapping(table.id, currentSourceMap as SourceMap)
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={`Configure ${table.name} mapping`}
            width={600}
            footer={
                <div className="flex justify-between items-center w-full">
                    <span className="text-sm text-muted">
                        {requiredFieldsConfigured}/{requiredFields.length} required fields configured
                    </span>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            onClick={handleTestMapping}
                            tooltip="Test the mapping by running the adapter query"
                            disabledReason={
                                requiredFieldsConfigured < requiredFields.length
                                    ? 'Configure all required fields first'
                                    : undefined
                            }
                        >
                            {testResult?.status === 'loading' ? (
                                <span className="flex items-center gap-1">
                                    <Spinner textColored className="text-sm" />
                                    Testing...
                                </span>
                            ) : (
                                'Test mapping'
                            )}
                        </LemonButton>
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
                    <h4 className="font-semibold mb-3">Required fields</h4>
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
                                <div className="flex-1">{renderColumnMappingCombobox(fieldName)}</div>
                            </div>
                        ))}
                    </div>
                </div>

                {optionalFields.length > 0 && (
                    <div>
                        <h4 className="font-semibold mb-3">Optional fields</h4>
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
                                    <div className="flex-1">{renderColumnMappingCombobox(fieldName)}</div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {testResult && testResult.status !== 'idle' && testResult.status !== 'loading' && (
                    <div
                        className={`p-3 rounded border ${
                            testResult.status === 'success'
                                ? 'bg-success-highlight border-success'
                                : 'bg-danger-highlight border-danger'
                        }`}
                    >
                        <div className="flex items-center gap-2">
                            {testResult.status === 'success' ? (
                                <IconCheck className="text-success" />
                            ) : (
                                <IconX className="text-danger" />
                            )}
                            <span className="text-sm font-medium">
                                {testResult.status === 'success'
                                    ? `Test passed - ${testResult.message}`
                                    : `Test failed - ${testResult.message}`}
                            </span>
                        </div>
                        {testResult.status === 'success' &&
                            testResult.columns &&
                            testResult.sample_data &&
                            testResult.sample_data.length > 0 && (
                                <div className="mt-3 overflow-x-auto max-h-60 overflow-y-auto">
                                    <table className="w-full text-xs border-collapse">
                                        <thead>
                                            <tr>
                                                {testResult.columns.map((col) => (
                                                    <th
                                                        key={col}
                                                        className="text-left p-1.5 border-b font-medium whitespace-nowrap"
                                                    >
                                                        {col}
                                                    </th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {testResult.sample_data.map((row, rowIdx) => (
                                                <tr key={rowIdx} className={rowIdx % 2 === 0 ? 'bg-bg-light' : ''}>
                                                    {row.map((cell: any, cellIdx: number) => (
                                                        <td
                                                            key={cellIdx}
                                                            className="p-1.5 border-b whitespace-nowrap max-w-48 truncate"
                                                            title={String(cell ?? '')}
                                                        >
                                                            {cell === null ? (
                                                                <span className="text-muted italic">null</span>
                                                            ) : (
                                                                String(cell)
                                                            )}
                                                        </td>
                                                    ))}
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
