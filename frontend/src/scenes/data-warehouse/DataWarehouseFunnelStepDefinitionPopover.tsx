import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { DataWarehousePopoverField, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { AnyPropertyFilter } from '~/types'

import { DataWarehouseTableForInsight } from './types'

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

    useEffect(() => {
        if (!isOpen) {
            return
        }

        setCustomName(initialValues.customName)
        setProperties(initialValues.properties)
        setFieldMappings(initialValues.fieldMappings)
    }, [initialValues, isOpen])

    const schemaColumns = useMemo(() => (table ? Object.values(table.fields ?? {}) : []), [table])

    const hasRequiredMappings = dataWarehousePopoverFields.every(
        ({ key, optional }) => optional || (key in fieldMappings && fieldMappings[key])
    )

    const saveDisabledReason = !table
        ? 'Select a data warehouse table first'
        : !hasRequiredMappings
          ? 'All required field mappings must be specified'
          : null

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
                    {dataWarehousePopoverFields.map(({ key, label, allowHogQL, hogQLOnly, optional, type }) => {
                        const fieldValue = fieldMappings[key]
                        const useHogQL = !!fieldValue && isUsingHogQLExpression(table, fieldValue)

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
                                            tableName={table.name}
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
                    })}
                </div>
            ) : null}
        </LemonModal>
    )
}
