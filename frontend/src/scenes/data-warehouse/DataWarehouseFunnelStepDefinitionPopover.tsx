import posthog from 'posthog-js'
import { useEffect, useMemo, useState } from 'react'

import {
    LemonButton,
    LemonDropdown,
    LemonInput,
    LemonLabel,
    LemonModal,
    LemonSegmentedButton,
    LemonSelect,
} from '@posthog/lemon-ui'

import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { DataWarehousePopoverField, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { hogqlQuery } from '~/queries/query'
import { hogql } from '~/queries/utils'
import { AnyPropertyFilter } from '~/types'

import { TablePreview } from './TablePreview'
import { DataWarehouseTableForInsight } from './types'

const AGGREGATION_TARGET_KEY_ORDER = ['distinct_id_field', 'timestamp_field', 'id_field'] as const
const AGGREGATION_TARGET_KEY_SET = new Set<string>(AGGREGATION_TARGET_KEY_ORDER)

const AGGREGATION_TARGET_LABELS: Record<(typeof AGGREGATION_TARGET_KEY_ORDER)[number], string> = {
    distinct_id_field: 'Aggregation target',
    timestamp_field: 'Timestamp',
    id_field: 'Unique ID',
}

interface DataWarehouseFunnelStepDefinitionModalValues {
    customName: string
    properties: AnyPropertyFilter[]
    fieldMappings: Record<string, string | null | undefined>
}

interface DataWarehouseFunnelStepDefinitionPopoverProps {
    isOpen: boolean
    table: DataWarehouseTableForInsight | null
    dataWarehousePopoverFields: DataWarehousePopoverField[]
    initialValues: DataWarehouseFunnelStepDefinitionModalValues
    onClose: () => void
    onSave: (values: DataWarehouseFunnelStepDefinitionModalValues) => void
}

const isUsingHogQLExpression = (table: DataWarehouseTableForInsight, value: string | undefined): boolean => {
    if (value === undefined) {
        return false
    }

    return !Object.values(table.fields ?? {}).some((column) => column.name === value)
}

export function DataWarehouseFunnelStepDefinitionPopover({
    isOpen,
    table,
    dataWarehousePopoverFields,
    initialValues,
    onClose,
    onSave,
}: DataWarehouseFunnelStepDefinitionPopoverProps): JSX.Element {
    const [customName, setCustomName] = useState(initialValues.customName)
    const [properties, setProperties] = useState<AnyPropertyFilter[]>(initialValues.properties)
    const [fieldMappings, setFieldMappings] = useState<Record<string, string | null | undefined>>(
        initialValues.fieldMappings
    )
    const [selectedAggregationTargetKey, setSelectedAggregationTargetKey] = useState<string | null>(null)
    const [tablePreviewData, setTablePreviewData] = useState<Record<string, any>[]>([])
    const [tablePreviewLoading, setTablePreviewLoading] = useState(false)

    useEffect(() => {
        if (!isOpen) {
            return
        }

        setCustomName(initialValues.customName)
        setProperties(initialValues.properties)
        setFieldMappings(initialValues.fieldMappings)
    }, [initialValues, isOpen])

    useEffect(() => {
        if (!isOpen || !table) {
            setTablePreviewData([])
            setTablePreviewLoading(false)
            return
        }

        let isCancelled = false
        setTablePreviewLoading(true)

        hogqlQuery(hogql`SELECT * FROM ${hogql.identifier(table.name)} LIMIT 10`)
            .then((response) => {
                if (isCancelled) {
                    return
                }

                const transformedData = (response.results || []).map((row: any[]) =>
                    Object.fromEntries(
                        (response.columns || []).map((column: string, index: number) => [column, row[index]])
                    )
                )
                setTablePreviewData(transformedData)
            })
            .catch((error) => {
                posthog.captureException(error)
                if (!isCancelled) {
                    setTablePreviewData([])
                }
            })
            .finally(() => {
                if (!isCancelled) {
                    setTablePreviewLoading(false)
                }
            })

        return () => {
            isCancelled = true
        }
    }, [isOpen, table?.name])

    const schemaColumns = useMemo(() => (table ? Object.values(table.fields ?? {}) : []), [table])
    const aggregationTargetFields = useMemo(() => {
        const fieldsByKey = new Map(dataWarehousePopoverFields.map((field) => [field.key, field]))
        return AGGREGATION_TARGET_KEY_ORDER.map((key) => fieldsByKey.get(key)).filter(
            (field): field is DataWarehousePopoverField => !!field
        )
    }, [dataWarehousePopoverFields])
    const nonAggregationTargetFields = useMemo(
        () => dataWarehousePopoverFields.filter((field) => !AGGREGATION_TARGET_KEY_SET.has(field.key)),
        [dataWarehousePopoverFields]
    )
    const selectedAggregationTargetField = useMemo(() => {
        if (!aggregationTargetFields.length) {
            return null
        }

        if (!selectedAggregationTargetKey) {
            return aggregationTargetFields[0]
        }

        return (
            aggregationTargetFields.find((field) => field.key === selectedAggregationTargetKey) ||
            aggregationTargetFields[0]
        )
    }, [aggregationTargetFields, selectedAggregationTargetKey])

    const hasRequiredMappings = dataWarehousePopoverFields.every(
        ({ key, optional }) => optional || (key in fieldMappings && fieldMappings[key])
    )

    const saveDisabledReason = !table
        ? 'Select a data warehouse table first'
        : !hasRequiredMappings
          ? 'All required field mappings must be specified'
          : null

    useEffect(() => {
        if (!isOpen) {
            return
        }

        setSelectedAggregationTargetKey(aggregationTargetFields[0]?.key || null)
    }, [isOpen, aggregationTargetFields])

    const renderFieldMapping = (
        { key, label, allowHogQL, hogQLOnly, optional, type }: DataWarehousePopoverField,
        currentTable: DataWarehouseTableForInsight
    ): JSX.Element => {
        const fieldValue = fieldMappings[key]
        const useHogQL = !!fieldValue && isUsingHogQLExpression(currentTable, fieldValue)

        return (
            <div key={key}>
                <div className="mb-1 text-sm font-medium">
                    {label}
                    {!optional && <span className="text-muted"> *</span>}
                </div>
                {!hogQLOnly && (
                    <LemonSelect
                        fullWidth
                        allowClear={!!optional}
                        value={useHogQL ? '' : (fieldValue ?? undefined)}
                        options={[
                            ...schemaColumns
                                .filter((column) => !type || column.type === type)
                                .map((column) => ({
                                    label: `${column.name} (${column.type})`,
                                    value: column.name,
                                })),
                            ...(allowHogQL ? [{ label: 'SQL expression', value: '' }] : []),
                        ]}
                        onChange={(value) =>
                            setFieldMappings((prev) => ({
                                ...prev,
                                [key]: value,
                            }))
                        }
                    />
                )}
                {((allowHogQL && useHogQL) || hogQLOnly) && (
                    <div className="mt-2">
                        <HogQLDropdown
                            hogQLValue={fieldValue || ''}
                            tableName={currentTable.name}
                            onHogQLValueChange={(value) =>
                                setFieldMappings((prev) => ({
                                    ...prev,
                                    [key]: value,
                                }))
                            }
                        />
                    </div>
                )}
            </div>
        )
    }

    return (
        <LemonModal
            title="Configure data warehouse funnel step"
            isOpen={isOpen}
            onClose={onClose}
            width={700}
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => onSave({ customName, properties, fieldMappings })}
                        disabledReason={saveDisabledReason}
                    >
                        Save step
                    </LemonButton>
                </div>
            }
        >
            {table ? (
                <div className="space-y-4">
                    <LemonLabel className="mb-1">Table</LemonLabel>
                    <LemonDropdown
                        // overlay={taxonomicFilter}
                        placement="bottom-start"
                        // visible={dropdownOpen}
                        // onClickOutside={closeDropdown}
                    >
                        <LemonButton
                            type="secondary"
                            // icon={!valuePresent ? <IconPlusSmall /> : undefined}
                            // data-attr={'property-select-toggle-' + index}
                            sideIcon={null} // The null sideIcon is here on purpose - it prevents the dropdown caret
                            // onClick={() => (dropdownOpen ? closeDropdown() : openDropdown())}
                            // size={size}
                            truncate={true}
                        >
                            {table.name}
                        </LemonButton>
                    </LemonDropdown>
                    <hr className="separator" />
                    <div>
                        <LemonLabel className="mb-1" showOptional>
                            Step name
                        </LemonLabel>
                        <LemonInput value={customName} onChange={setCustomName} placeholder="Step name" fullWidth />
                    </div>
                    <div>
                        <LemonLabel className="mb-1">Properties</LemonLabel>
                        <PropertyFilters
                            pageKey={`dw-funnel-step-properties-${table.name}`}
                            propertyFilters={properties}
                            onChange={setProperties}
                            taxonomicGroupTypes={[
                                TaxonomicFilterGroupType.DataWarehouseProperties,
                                TaxonomicFilterGroupType.HogQLExpression,
                            ]}
                            schemaColumns={schemaColumns}
                            dataWarehouseTableName={table.name}
                        />
                    </div>
                    <hr className="separator" />
                    {aggregationTargetFields.length > 1 && (
                        <div>
                            <LemonLabel className="mb-1">Configuration</LemonLabel>
                            <LemonSegmentedButton
                                fullWidth
                                value={selectedAggregationTargetField?.key}
                                onChange={(value) => setSelectedAggregationTargetKey(String(value))}
                                options={aggregationTargetFields.map((field) => ({
                                    value: field.key,
                                    label: AGGREGATION_TARGET_LABELS[
                                        field.key as keyof typeof AGGREGATION_TARGET_LABELS
                                    ],
                                }))}
                            />
                        </div>
                    )}
                    {selectedAggregationTargetField ? renderFieldMapping(selectedAggregationTargetField, table) : null}
                    {nonAggregationTargetFields.map((field) => renderFieldMapping(field, table))}
                    <div>
                        <LemonLabel className="mb-1">Table preview</LemonLabel>
                        <TablePreview
                            table={table}
                            emptyMessage="Select a data warehouse table first"
                            previewData={tablePreviewData}
                            loading={tablePreviewLoading}
                        />
                    </div>
                </div>
            ) : null}
        </LemonModal>
    )
}
