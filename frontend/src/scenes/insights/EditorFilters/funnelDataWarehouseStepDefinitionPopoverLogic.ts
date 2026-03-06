import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import type { TablePreviewExpressionColumn } from 'lib/components/TablePreview/types'
import type {
    DataWarehousePopoverField,
    TaxonomicFilterGroup,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import type { DatabaseSerializedFieldType } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import type { funnelDataWarehouseStepDefinitionPopoverLogicType } from './funnelDataWarehouseStepDefinitionPopoverLogicType'

export type FunnelFieldKey = 'id_field' | 'timestamp_field' | 'distinct_id_field'

export const EDITABLE_FIELD_ORDER: FunnelFieldKey[] = ['distinct_id_field', 'timestamp_field', 'id_field']
const ALLOWED_COLUMN_TYPES_BY_FIELD_KEY: Record<FunnelFieldKey, DatabaseSerializedFieldType[]> = {
    distinct_id_field: ['string'],
    timestamp_field: ['datetime', 'date', 'string'],
    id_field: ['string', 'integer', 'decimal', 'float'],
}

export interface FunnelDataWarehouseStepDefinitionPopoverLogicProps {
    table: DataWarehouseTableForInsight
    group: TaxonomicFilterGroup
    dataWarehousePopoverFields: DataWarehousePopoverField[]
    onSelectItem: (group: TaxonomicFilterGroup, value: TaxonomicFilterValue | null, item: any) => void
    insightProps: InsightLogicProps
}

export const funnelDataWarehouseStepDefinitionPopoverLogic = kea<funnelDataWarehouseStepDefinitionPopoverLogicType>([
    props({} as FunnelDataWarehouseStepDefinitionPopoverLogicProps),
    key((props) => props.table.name),
    path((key) => ['scenes', 'insights', 'EditorFilters', 'funnelDataWarehouseStepDefinitionPopoverLogic', key]),
    connect((props: FunnelDataWarehouseStepDefinitionPopoverLogicProps) => ({
        values: [definitionPopoverLogic, ['localDefinition'], funnelDataLogic(props.insightProps), ['querySource']],
        actions: [definitionPopoverLogic, ['setLocalDefinition']],
    })),
    actions(() => ({
        setActiveFieldKey: (activeFieldKey: FunnelFieldKey) => ({ activeFieldKey }),
        selectTable: true,
    })),
    selectors({
        dataWarehousePopoverFields: [(_, props) => [props.dataWarehousePopoverFields], (fields) => fields],
    }),
    reducers({
        activeFieldKey: [
            'distinct_id_field' as FunnelFieldKey,
            {
                setActiveFieldKey: (_, { activeFieldKey }) => activeFieldKey,
            },
        ],
    }),
    selectors({
        columnOptions: [
            (_, p) => [p.table],
            (table) =>
                Object.values(table.fields).map((column) => ({
                    label: `${column.name} (${column.type})`,
                    value: column.name,
                    type: column.type,
                })),
        ],
        activeFieldKeyOptions: [
            (s) => [s.dataWarehousePopoverFields],
            (dataWarehousePopoverFields) =>
                EDITABLE_FIELD_ORDER.map((key) => ({
                    value: key,
                    label: dataWarehousePopoverFields.find((f) => f.key === key)?.label ?? key,
                })),
        ],
        activeField: [
            (s) => [s.dataWarehousePopoverFields, s.activeFieldKey],
            (dataWarehousePopoverFields, activeFieldKey) =>
                dataWarehousePopoverFields.find((f) => f.key === activeFieldKey),
        ],
        activeFieldValue: [
            (s) => [s.localDefinition, s.activeFieldKey],
            (localDefinition, activeFieldKey) => localDefinition[activeFieldKey],
        ],
        tableFieldNames: [
            (_, props) => [props.table],
            (table) => new Set(Object.values(table.fields).map((field) => field.name)),
        ],
        previewExpressionColumns: [
            (s) => [s.dataWarehousePopoverFields, s.localDefinition, s.tableFieldNames],
            (dataWarehousePopoverFields, localDefinition, tableFieldNames): TablePreviewExpressionColumn[] => {
                const usedKeys = new Set(tableFieldNames)

                return EDITABLE_FIELD_ORDER.flatMap((fieldKey) => {
                    const configuredValue = localDefinition[fieldKey]
                    if (typeof configuredValue !== 'string') {
                        return []
                    }

                    const expression = configuredValue.trim()
                    if (!expression || tableFieldNames.has(expression)) {
                        return []
                    }

                    const label = dataWarehousePopoverFields.find((field) => field.key === fieldKey)?.label ?? fieldKey
                    const keyBase = `__${fieldKey}_hogql_expression`
                    let key = keyBase
                    let suffix = 2

                    while (usedKeys.has(key)) {
                        key = `${keyBase}_${suffix}`
                        suffix += 1
                    }

                    usedKeys.add(key)

                    return [
                        {
                            key,
                            expression,
                            label: `${label} (SQL expression)`,
                            type: 'SQL expression',
                        },
                    ]
                })
            },
        ],
        selectedPreviewKey: [
            (s) => [s.previewExpressionColumns, s.activeFieldKey, s.activeFieldValue],
            (previewExpressionColumns, activeFieldKey, activeFieldValue) =>
                previewExpressionColumns.find((column) => column.key.startsWith(`__${activeFieldKey}_hogql_expression`))
                    ?.key ?? activeFieldValue,
        ],
        activeFieldOptions: [
            (s) => [s.columnOptions, s.activeField, s.activeFieldKey],
            (columnOptions, activeField, activeFieldKey) => {
                const filteredColumnOptions = columnOptions.filter((column) =>
                    ALLOWED_COLUMN_TYPES_BY_FIELD_KEY[activeFieldKey].includes(column.type)
                )

                return activeField
                    ? [
                          ...filteredColumnOptions,
                          ...(activeField.allowHogQL ? [{ label: 'SQL Expression', value: '' }] : []),
                      ]
                    : filteredColumnOptions
            },
        ],
        activeFieldIsHogQL: [
            (s, p) => [s.activeFieldValue, p.table],
            (activeFieldValue, table) => !Object.values(table.fields).some((field) => field.name === activeFieldValue),
        ],
        isAggregatingByGroup: [
            (s) => [s.querySource],
            (querySource) => querySource?.aggregation_group_type_index != null,
        ],
        isAggregatingByHogQL: [
            (s) => [s.querySource, s.isAggregatingByGroup],
            (querySource, isAggregatingByGroup) =>
                Boolean(querySource?.funnelsFilter?.funnelAggregateByHogQL) && !isAggregatingByGroup,
        ],
    }),
    listeners(({ values, props }) => ({
        selectTable: () => {
            props.onSelectItem(props.group, props.table.name, values.localDefinition)
            posthog.capture('funnel data warehouse step selected')
        },
    })),
    afterMount(() => {
        posthog.capture('funnel data warehouse step popover viewed')
    }),
])
