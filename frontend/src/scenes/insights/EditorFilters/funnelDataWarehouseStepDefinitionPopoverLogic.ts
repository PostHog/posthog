import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import type {
    DataWarehousePopoverField,
    TaxonomicFilterGroup,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { InsightLogicProps } from '~/types'

import type { funnelDataWarehouseStepDefinitionPopoverLogicType } from './funnelDataWarehouseStepDefinitionPopoverLogicType'

export type FunnelFieldKey = 'id_field' | 'timestamp_field' | 'distinct_id_field'

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
    connect((props) => ({
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
        activeField: [
            (s) => [s.dataWarehousePopoverFields, s.activeFieldKey],
            (dataWarehousePopoverFields, activeFieldKey) =>
                dataWarehousePopoverFields.find((f) => f.key === activeFieldKey),
        ],
        activeFieldValue: [
            (s) => [s.localDefinition, s.activeFieldKey],
            (localDefinition, activeFieldKey) => localDefinition[activeFieldKey],
        ],
        activeFieldOptions: [
            (s) => [s.columnOptions, s.activeField],
            (columnOptions, activeField) =>
                activeField
                    ? [
                          ...columnOptions.filter((column) => !activeField.type || column.type === activeField.type),
                          ...(activeField.allowHogQL ? [{ label: 'SQL Expression', value: '' }] : []),
                      ]
                    : columnOptions,
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
        },
    })),
])
