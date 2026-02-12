import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    DataWarehousePopoverField,
    DefinitionPopoverRendererProps,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { hogqlQuery } from '~/queries/query'
import { hogql } from '~/queries/utils'

import { TablePreview } from './TablePreview'
import { DataWarehouseTableForInsight } from './types'

const TIMESTAMP_FIELD_FALLBACKS = ['created', 'created_at', 'createdAt', 'updated', 'updated_at', 'updatedAt']
const HOGQL_OPTION = { label: 'SQL Expression', value: '' }

type FunnelFieldKey = 'distinct_id_field' | 'timestamp_field' | 'id_field'

const EDITABLE_FIELD_MAP: Record<
    FunnelFieldKey,
    { segmentedLabel: string; fallbackLabel: string; fallbackAllowHogQL?: boolean }
> = {
    distinct_id_field: {
        segmentedLabel: 'Aggregation target',
        fallbackLabel: 'Distinct ID Field',
        fallbackAllowHogQL: true,
    },
    timestamp_field: {
        segmentedLabel: 'Timestamp',
        fallbackLabel: 'Timestamp Field',
        fallbackAllowHogQL: true,
    },
    id_field: {
        segmentedLabel: 'Unique ID',
        fallbackLabel: 'ID Field',
    },
}

const EDITABLE_FIELD_ORDER: FunnelFieldKey[] = ['distinct_id_field', 'timestamp_field', 'id_field']

function resolveTimestampField(table: DataWarehouseTableForInsight, configuredTimestampField?: string): string | null {
    const tableFieldNames = new Set(Object.values(table.fields).map((field) => field.name))

    if (configuredTimestampField) {
        return tableFieldNames.has(configuredTimestampField) ? configuredTimestampField : null
    }

    const fallbackFieldFromName = Object.values(table.fields).find((field) =>
        TIMESTAMP_FIELD_FALLBACKS.includes(field.name)
    )
    if (fallbackFieldFromName) {
        return fallbackFieldFromName.name
    }

    const fallbackFieldFromType = Object.values(table.fields).find(
        (field) => field.type === 'datetime' || field.type === 'date'
    )
    return fallbackFieldFromType?.name ?? null
}

function transformPreviewResponse(response: { columns?: string[]; results?: any[][] }): Record<string, any>[] {
    return (response.results || []).map((row: any[]) =>
        Object.fromEntries((response.columns || []).map((column: string, index: number) => [column, row[index]]))
    )
}

function getConfiguredFieldValue(
    localDefinition: Partial<DataWarehouseTableForInsight>,
    key: FunnelFieldKey
): string | undefined {
    const fieldValue = localDefinition[key]
    return typeof fieldValue === 'string' ? fieldValue : undefined
}

function isUsingHogQLExpression(fieldValue: string | undefined, table: DataWarehouseTableForInsight): boolean {
    if (fieldValue === undefined) {
        return false
    }
    return !Object.values(table.fields).some((field) => field.name === fieldValue)
}

export function DataWarehouseFunnelStepDefinitionPopover({
    item,
    group,
}: DefinitionPopoverRendererProps): JSX.Element | null {
    if (group.type !== TaxonomicFilterGroupType.DataWarehouse || !('fields' in item)) {
        return null
    }

    const { setLocalDefinition } = useActions(definitionPopoverLogic)
    const { selectItem } = useActions(taxonomicFilterLogic)
    const { insightProps } = useValues(insightLogic)
    const { querySource, insightData } = useValues(funnelDataLogic(insightProps))
    const { localDefinition } = useValues(definitionPopoverLogic)
    const { dataWarehousePopoverFields, selectedItemMeta } = useValues(taxonomicFilterLogic)

    const [previewData, setPreviewData] = useState<Record<string, any>[]>([])
    const [previewLoading, setPreviewLoading] = useState(false)
    const [activeFieldKey, setActiveFieldKey] = useState<FunnelFieldKey>('distinct_id_field')

    const table = item as DataWarehouseTableForInsight
    const dataWarehouseLocalDefinition = localDefinition as Partial<DataWarehouseTableForInsight>
    const configuredTimestampField = getConfiguredFieldValue(dataWarehouseLocalDefinition, 'timestamp_field')
    const timestampField = useMemo(
        () => resolveTimestampField(table, configuredTimestampField),
        [configuredTimestampField, table]
    )
    const editableFieldsByKey = useMemo(() => {
        const fieldsByKey = new Map<FunnelFieldKey, DataWarehousePopoverField>()
        for (const key of EDITABLE_FIELD_ORDER) {
            const existingField = dataWarehousePopoverFields.find((field) => field.key === key)
            fieldsByKey.set(
                key,
                existingField ?? {
                    key,
                    label: EDITABLE_FIELD_MAP[key].fallbackLabel,
                    allowHogQL: EDITABLE_FIELD_MAP[key].fallbackAllowHogQL,
                }
            )
        }
        return fieldsByKey
    }, [dataWarehousePopoverFields])
    const activeField = editableFieldsByKey.get(activeFieldKey)
    const activeFieldValue = getConfiguredFieldValue(dataWarehouseLocalDefinition, activeFieldKey)
    const activeFieldIsHogQL = isUsingHogQLExpression(activeFieldValue, table)
    const activeFieldSelectValue = activeFieldIsHogQL ? '' : activeFieldValue
    const selectedItemValue = group.getValue?.(dataWarehouseLocalDefinition) ?? null

    const columnOptions = useMemo(
        () =>
            Object.values(table.fields).map((column) => ({
                label: `${column.name} (${column.type})`,
                value: column.name,
                type: column.type,
            })),
        [table.fields]
    )
    const activeFieldOptions = useMemo(() => {
        if (!activeField) {
            return []
        }
        return [
            ...columnOptions.filter((column) => !activeField.type || column.type === activeField.type),
            ...(activeField.allowHogQL ? [HOGQL_OPTION] : []),
        ]
    }, [activeField, columnOptions])

    // Keep the selected funnel mappings when opening the popover for an already configured table.
    useEffect(() => {
        if (selectedItemMeta && table.name === selectedItemMeta.id) {
            setLocalDefinition(selectedItemMeta)
        }
    }, [table.name]) // eslint-disable-line react-hooks/exhaustive-deps

    const tableName = table.name
    const dateFrom = insightData?.resolved_date_range?.date_from ?? querySource?.dateRange?.date_from
    const dateTo = insightData?.resolved_date_range?.date_to ?? querySource?.dateRange?.date_to

    useEffect(() => {
        let isCanceled = false

        const loadPreview = async (): Promise<void> => {
            setPreviewLoading(true)
            try {
                const parsedDateFrom = dateFrom && dateFrom !== 'all' ? dayjs(dateFrom) : null
                const parsedDateTo = dateTo && dateTo !== 'all' ? dayjs(dateTo) : null
                const filters: string[] = []
                if (timestampField && parsedDateFrom?.isValid()) {
                    filters.push(String(hogql`${hogql.identifier(timestampField)} >= ${parsedDateFrom}`))
                }
                if (timestampField && parsedDateTo?.isValid()) {
                    filters.push(String(hogql`${hogql.identifier(timestampField)} <= ${parsedDateTo}`))
                }

                const whereClause = filters.length > 0 ? ` WHERE ${filters.join(' AND ')}` : ''
                const previewQuery = hogql`SELECT * FROM ${hogql.identifier(tableName)}${hogql.raw(
                    whereClause
                )} LIMIT 10`
                const response = await hogqlQuery(previewQuery)

                if (!isCanceled) {
                    setPreviewData(transformPreviewResponse(response))
                }
            } catch (error) {
                posthog.captureException(error)
                if (!isCanceled) {
                    setPreviewData([])
                }
            } finally {
                if (!isCanceled) {
                    setPreviewLoading(false)
                }
            }
        }

        void loadPreview()

        return () => {
            isCanceled = true
        }
    }, [dateFrom, dateTo, tableName, timestampField])

    return (
        <div className="space-y-3 w-100">
            <TablePreview
                table={table}
                emptyMessage="Select a data warehouse table to view preview"
                previewData={previewData}
                loading={previewLoading}
                selectedKey={activeFieldValue ?? timestampField}
                heightClassName="h-48"
            />
            {activeField && (
                <form className="definition-popover-data-warehouse-schema-form">
                    <div className="flex flex-col justify-between gap-4">
                        <LemonSegmentedButton
                            fullWidth
                            value={activeFieldKey}
                            onChange={(value) => setActiveFieldKey(value as FunnelFieldKey)}
                            options={EDITABLE_FIELD_ORDER.map((key) => ({
                                value: key,
                                label: EDITABLE_FIELD_MAP[key].segmentedLabel,
                            }))}
                        />
                        <label className="definition-popover-edit-form-label" htmlFor={activeField.key}>
                            <span className="label-text font-semibold">{activeField.label}</span>
                        </label>
                        {!activeField.hogQLOnly && (
                            <LemonSelect
                                fullWidth
                                allowClear={!!activeField.optional}
                                value={activeFieldSelectValue}
                                options={activeFieldOptions}
                                onChange={(value: string | null) =>
                                    setLocalDefinition({
                                        [activeFieldKey]: value ?? undefined,
                                    } as Partial<DataWarehouseTableForInsight>)
                                }
                            />
                        )}
                        {((activeField.allowHogQL && activeFieldIsHogQL) || activeField.hogQLOnly) && (
                            <HogQLDropdown
                                hogQLValue={activeFieldValue || ''}
                                tableName={activeField.tableName || table.name}
                                onHogQLValueChange={(value) =>
                                    setLocalDefinition({
                                        [activeFieldKey]: value,
                                    } as Partial<DataWarehouseTableForInsight>)
                                }
                            />
                        )}
                        <div className="flex justify-end">
                            <LemonButton
                                onClick={() => {
                                    selectItem(group, selectedItemValue, dataWarehouseLocalDefinition, undefined)
                                }}
                                disabledReason={
                                    dataWarehousePopoverFields.every(
                                        ({ key, optional }: DataWarehousePopoverField) =>
                                            optional ||
                                            (key in dataWarehouseLocalDefinition &&
                                                Boolean((dataWarehouseLocalDefinition as Record<string, unknown>)[key]))
                                    )
                                        ? null
                                        : 'All required field mappings must be specified'
                                }
                                type="primary"
                            >
                                Select
                            </LemonButton>
                        </div>
                    </div>
                </form>
            )}
        </div>
    )
}
