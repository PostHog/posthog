import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo, useState } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    DataWarehousePopoverField,
    DefinitionPopoverRendererProps,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'

import { hogqlQuery } from '~/queries/query'
import { DataWarehouseNode, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

import { TablePreview } from './TablePreview'
import { DataWarehouseTableForInsight } from './types'

const TIMESTAMP_FIELD_FALLBACKS = ['created', 'created_at', 'createdAt', 'updated', 'updated_at', 'updatedAt']
const HOGQL_OPTION = { label: 'SQL Expression', value: '' }
const AGGREGATION_MATCH_SAMPLE_LIMIT = 10000
const SIMPLE_IDENTIFIER_REGEX = /^[A-Za-z_][A-Za-z0-9_]*$/

type FunnelFieldKey = 'distinct_id_field' | 'timestamp_field' | 'id_field'
type PreviewExpressionColumn = {
    fieldKey: FunnelFieldKey
    expression: string
    alias: string
    label: string
}
type AdjacentDataWarehouseStep = {
    direction: 'previous' | 'next'
    step: DataWarehouseNode
}

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
const EDITABLE_FIELD_EXPLANATION: Record<FunnelFieldKey, string> = {
    distinct_id_field: 'Used to match people or groups across funnel steps.',
    timestamp_field: 'Used to order step timing and apply the funnel date range.',
    id_field: 'Used as the unique row ID to detect missing or duplicate records.',
}

function resolveTimestampField(table: DataWarehouseTableForInsight, configuredTimestampField?: string): string | null {
    const tableFieldNames = new Set(Object.values(table.fields).map((field) => field.name))

    if (configuredTimestampField && tableFieldNames.has(configuredTimestampField)) {
        return configuredTimestampField
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

function resolveFieldExpression(fieldValue: string | undefined, tableFieldNames?: Set<string>): string | null {
    const trimmedValue = fieldValue?.trim()
    if (!trimmedValue) {
        return null
    }

    if ((tableFieldNames && tableFieldNames.has(trimmedValue)) || SIMPLE_IDENTIFIER_REGEX.test(trimmedValue)) {
        return String(hogql`${hogql.identifier(trimmedValue)}`)
    }

    return String(hogql`${hogql.raw(trimmedValue)}`)
}

function parseNumericResult(value: unknown): number {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : 0
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
    const [validationLoading, setValidationLoading] = useState(false)
    const [validationErrors, setValidationErrors] = useState<string[]>([])
    const [validationWarnings, setValidationWarnings] = useState<string[]>([])
    const [validationSucceeded, setValidationSucceeded] = useState(false)
    const [validationHasRun, setValidationHasRun] = useState(false)

    const table = item as DataWarehouseTableForInsight
    const previewTable = useMemo(() => {
        const nonLazyFields = Object.values(table.fields).filter((field) => field.type !== 'lazy_table')
        const hasLazyTableFields = nonLazyFields.length !== Object.values(table.fields).length
        if (!hasLazyTableFields) {
            return table
        }

        return {
            ...table,
            fields: Object.fromEntries(nonLazyFields.map((field) => [field.name, field])),
        }
    }, [table])
    const previewLazyColumns = useMemo(
        () =>
            Object.values(table.fields)
                .filter((field) => field.type === 'lazy_table')
                .map((field) => ({
                    key: field.name,
                    label: field.name,
                    type: field.type,
                })),
        [table.fields]
    )
    const tableName = table.name
    const dataWarehouseLocalDefinition = localDefinition as Partial<DataWarehouseTableForInsight>
    const configuredIdField = getConfiguredFieldValue(dataWarehouseLocalDefinition, 'id_field')
    const configuredTimestampField = getConfiguredFieldValue(dataWarehouseLocalDefinition, 'timestamp_field')
    const configuredAggregationTargetField = getConfiguredFieldValue(dataWarehouseLocalDefinition, 'distinct_id_field')
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
    const tableFieldNames = useMemo(
        () => new Set(Object.values(table.fields).map((field) => field.name)),
        [table.fields]
    )
    const previewExpressionColumns = useMemo<PreviewExpressionColumn[]>(() => {
        const expressionColumns: PreviewExpressionColumn[] = []
        const usedAliases = new Set(tableFieldNames)

        for (const fieldKey of EDITABLE_FIELD_ORDER) {
            const configuredValue = getConfiguredFieldValue(dataWarehouseLocalDefinition, fieldKey)?.trim()
            if (!configuredValue || tableFieldNames.has(configuredValue)) {
                continue
            }

            const label = editableFieldsByKey.get(fieldKey)?.label ?? EDITABLE_FIELD_MAP[fieldKey].fallbackLabel
            const aliasBase = `__${fieldKey}_sql_expression`
            let alias = aliasBase
            let suffix = 2
            while (usedAliases.has(alias)) {
                alias = `${aliasBase}_${suffix}`
                suffix += 1
            }
            usedAliases.add(alias)

            expressionColumns.push({
                fieldKey,
                expression: configuredValue,
                alias,
                label: `${label} (SQL expression)`,
            })
        }

        return expressionColumns
    }, [dataWarehouseLocalDefinition, editableFieldsByKey, tableFieldNames])
    const activeExpressionColumn = previewExpressionColumns.find((column) => column.fieldKey === activeFieldKey)
    const selectedPreviewKey = activeExpressionColumn?.alias ?? activeFieldValue ?? timestampField

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
        if (!selectedItemMeta || table.name !== selectedItemMeta.id) {
            return
        }
        setLocalDefinition(selectedItemMeta)
    }, [selectedItemMeta, setLocalDefinition, table.name])

    const dateFrom = insightData?.resolved_date_range?.date_from ?? querySource?.dateRange?.date_from
    const dateTo = insightData?.resolved_date_range?.date_to ?? querySource?.dateRange?.date_to
    const isGroupAggregationTarget =
        querySource?.aggregation_group_type_index !== undefined && querySource?.aggregation_group_type_index !== null
    const isCustomAggregationTarget =
        Boolean(querySource?.funnelsFilter?.funnelAggregateByHogQL) && !isGroupAggregationTarget
    const aggregationTargetIdLabel = isGroupAggregationTarget ? 'group ID' : 'person ID'
    const selectedStepOrder = useMemo(() => {
        const selectedOrder = (selectedItemMeta as { order?: unknown } | null)?.order
        if (typeof selectedOrder === 'number') {
            return selectedOrder
        }
        if (!querySource) {
            return null
        }
        const fallbackOrder = querySource.series.findIndex(
            (seriesItem) => seriesItem.kind === NodeKind.DataWarehouseNode && seriesItem.table_name === tableName
        )
        return fallbackOrder >= 0 ? fallbackOrder : null
    }, [querySource, selectedItemMeta, tableName])
    const adjacentDataWarehouseSteps = useMemo<AdjacentDataWarehouseStep[]>(() => {
        if (!querySource || selectedStepOrder === null) {
            return []
        }

        const adjacentSteps: AdjacentDataWarehouseStep[] = []
        const previousStep = querySource.series[selectedStepOrder - 1]
        if (previousStep?.kind === NodeKind.DataWarehouseNode) {
            adjacentSteps.push({
                direction: 'previous',
                step: previousStep,
            })
        }

        const nextStep = querySource.series[selectedStepOrder + 1]
        if (nextStep?.kind === NodeKind.DataWarehouseNode) {
            adjacentSteps.push({
                direction: 'next',
                step: nextStep,
            })
        }

        return adjacentSteps
    }, [querySource, selectedStepOrder])
    const requiredMappingsConfigured = dataWarehousePopoverFields.every(
        ({ key, optional }: DataWarehousePopoverField) =>
            optional ||
            (key in dataWarehouseLocalDefinition &&
                Boolean((dataWarehouseLocalDefinition as Record<string, unknown>)[key]))
    )

    useEffect(() => {
        setValidationErrors([])
        setValidationWarnings([])
        setValidationSucceeded(false)
        setValidationHasRun(false)
    }, [configuredAggregationTargetField, configuredIdField, configuredTimestampField, tableName])

    const validateConfiguredFields = async (): Promise<void> => {
        setValidationHasRun(true)
        setValidationLoading(true)
        setValidationErrors([])
        setValidationWarnings([])
        setValidationSucceeded(false)

        const errors: string[] = []
        const warnings: string[] = []

        const idExpression = resolveFieldExpression(configuredIdField, tableFieldNames)
        const timestampExpression = resolveFieldExpression(configuredTimestampField, tableFieldNames)
        const aggregationTargetExpression = resolveFieldExpression(configuredAggregationTargetField, tableFieldNames)

        if (!idExpression) {
            errors.push('Unique ID is required.')
        }
        if (!timestampExpression) {
            errors.push('Timestamp is required.')
        }
        if (!aggregationTargetExpression) {
            errors.push('Aggregation target is required.')
        }

        if (errors.length > 0) {
            setValidationErrors(errors)
            setValidationLoading(false)
            return
        }

        try {
            const validationResponse = await hogqlQuery(hogql`
                SELECT
                    countIf(id_value IS NULL) AS id_null_count,
                    (countIf(id_value IS NOT NULL) - uniqExactIf(id_value, id_value IS NOT NULL)) AS id_duplicate_count,
                    countIf(timestamp_value IS NULL) AS timestamp_null_count,
                    countIf(timestamp_value IS NOT NULL AND parseDateTimeBestEffortOrNull(toString(timestamp_value)) IS NULL) AS timestamp_invalid_count,
                    countIf(aggregation_target_value IS NULL) AS aggregation_target_null_count
                FROM (
                    SELECT
                        ${hogql.raw(idExpression)} AS id_value,
                        ${hogql.raw(timestampExpression)} AS timestamp_value,
                        ${hogql.raw(aggregationTargetExpression)} AS aggregation_target_value
                    FROM ${hogql.identifier(tableName)}
                ) AS validation_rows
            `)
            const validationRow = validationResponse.results?.[0] ?? []
            const idNullCount = parseNumericResult(validationRow[0])
            const idDuplicateCount = parseNumericResult(validationRow[1])
            const timestampNullCount = parseNumericResult(validationRow[2])
            const timestampInvalidCount = parseNumericResult(validationRow[3])
            const aggregationTargetNullCount = parseNumericResult(validationRow[4])

            if (idNullCount > 0) {
                errors.push(`Unique ID has ${idNullCount.toLocaleString()} null values.`)
            }
            if (idDuplicateCount > 0) {
                errors.push(`Unique ID has ${idDuplicateCount.toLocaleString()} duplicate values.`)
            }
            if (timestampNullCount > 0) {
                errors.push(`Timestamp has ${timestampNullCount.toLocaleString()} null values.`)
            }
            if (timestampInvalidCount > 0) {
                errors.push(
                    `Timestamp has ${timestampInvalidCount.toLocaleString()} values that are not valid timestamps.`
                )
            }
            if (aggregationTargetNullCount > 0) {
                errors.push(`Aggregation target has ${aggregationTargetNullCount.toLocaleString()} null values.`)
            }

            for (const { direction, step } of adjacentDataWarehouseSteps) {
                const adjacentExpression = resolveFieldExpression(step.distinct_id_field)
                if (!adjacentExpression) {
                    continue
                }

                const overlapResponse = await hogqlQuery(hogql`
                    SELECT count() AS overlap_count
                    FROM (
                        SELECT DISTINCT aggregation_target_value
                        FROM (
                            SELECT ${hogql.raw(aggregationTargetExpression)} AS aggregation_target_value
                            FROM ${hogql.identifier(tableName)}
                        ) AS current_step
                        WHERE aggregation_target_value IS NOT NULL
                        LIMIT ${AGGREGATION_MATCH_SAMPLE_LIMIT}
                    ) AS current_targets
                    ANY INNER JOIN (
                        SELECT DISTINCT adjacent_target_value
                        FROM (
                            SELECT ${hogql.raw(adjacentExpression)} AS adjacent_target_value
                            FROM ${hogql.identifier(step.table_name)}
                        ) AS adjacent_step
                        WHERE adjacent_target_value IS NOT NULL
                        LIMIT ${AGGREGATION_MATCH_SAMPLE_LIMIT}
                    ) AS adjacent_targets
                    ON current_targets.aggregation_target_value = adjacent_targets.adjacent_target_value
                `)
                const overlapCount = parseNumericResult(overlapResponse.results?.[0]?.[0])

                if (overlapCount === 0) {
                    warnings.push(
                        `No aggregation target overlap found with the ${direction} step (${step.table_name}) in a ${AGGREGATION_MATCH_SAMPLE_LIMIT.toLocaleString()}-value sample. There might not be data for this funnel yet.`
                    )
                }
            }
        } catch (error) {
            posthog.captureException(error)
            errors.push('Validation failed. Check your field mappings and SQL expressions, then try again.')
        } finally {
            setValidationErrors(errors)
            setValidationWarnings(warnings)
            setValidationSucceeded(errors.length === 0)
            setValidationLoading(false)
        }
    }

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
                const previewExpressionSelectClause =
                    previewExpressionColumns.length > 0
                        ? `, ${previewExpressionColumns
                              .map(({ expression, alias }) =>
                                  String(hogql`${hogql.raw(expression)} AS ${hogql.identifier(alias)}`)
                              )
                              .join(', ')}`
                        : ''
                const previewQuery = hogql`SELECT *${hogql.raw(previewExpressionSelectClause)} FROM ${hogql.identifier(
                    tableName
                )}${hogql.raw(whereClause)} LIMIT 10`
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
    }, [dateFrom, dateTo, previewExpressionColumns, tableName, timestampField])

    return (
        <div className="space-y-3 w-100">
            <TablePreview
                table={previewTable}
                emptyMessage="Select a data warehouse table to view preview"
                previewData={previewData}
                loading={previewLoading}
                selectedKey={selectedPreviewKey}
                extraColumns={[
                    ...previewExpressionColumns.map(({ alias, label }) => ({
                        key: alias,
                        label,
                        type: 'SQL expression',
                    })),
                    ...previewLazyColumns,
                ]}
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
                        <div className="text-secondary text-xs">{EDITABLE_FIELD_EXPLANATION[activeFieldKey]}</div>
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
                        {activeFieldKey === 'distinct_id_field' && (
                            <div className="text-secondary text-xs">
                                {isCustomAggregationTarget ? (
                                    <span>
                                        Current aggregation target is custom. The selected field needs to match the
                                        custom aggregation value.
                                    </span>
                                ) : (
                                    <>
                                        <div>
                                            Current aggregation target is set to{' '}
                                            <b>{isGroupAggregationTarget ? 'group' : 'person'}</b>, so the selected
                                            field needs to match the <b>{aggregationTargetIdLabel}</b>.
                                        </div>
                                        <div className="mt-1">
                                            If this field is not directly available on the table, add it by joining in{' '}
                                            <Link to={urls.sqlEditor()} target="_blank">
                                                SQL editor
                                            </Link>{' '}
                                            using fields like <code>distinct_id</code> or <code>email</code>.{' '}
                                            <Link
                                                to="https://posthog.com/docs/data-warehouse/views#joining-tables"
                                                target="_blank"
                                            >
                                                For more help
                                            </Link>
                                            .
                                        </div>
                                    </>
                                )}
                            </div>
                        )}
                        {validationErrors.length > 0 && (
                            <LemonBanner
                                type="error"
                                children={
                                    <ul className="mb-0 pl-4 list-disc">
                                        {validationErrors.map((errorMessage) => (
                                            <li key={errorMessage}>{errorMessage}</li>
                                        ))}
                                    </ul>
                                }
                            />
                        )}
                        {validationWarnings.length > 0 && (
                            <LemonBanner
                                type="warning"
                                children={
                                    <ul className="mb-0 pl-4 list-disc">
                                        {validationWarnings.map((warningMessage) => (
                                            <li key={warningMessage}>{warningMessage}</li>
                                        ))}
                                    </ul>
                                }
                            />
                        )}
                        <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                                <LemonButton
                                    type="secondary"
                                    loading={validationLoading}
                                    onClick={validateConfiguredFields}
                                >
                                    Validate
                                </LemonButton>
                                {validationHasRun && validationSucceeded && !validationLoading && (
                                    <span className="inline-flex items-center gap-1 text-success text-xs font-medium">
                                        <IconCheckCircle />
                                        Validation passed
                                    </span>
                                )}
                            </div>
                            <LemonButton
                                onClick={() => {
                                    selectItem(group, selectedItemValue, dataWarehouseLocalDefinition, undefined)
                                }}
                                disabledReason={
                                    requiredMappingsConfigured ? null : 'All required field mappings must be specified'
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
