import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightLogicProps } from '~/types'

export type FunnelFieldKey = 'id_field' | 'timestamp_field' | 'distinct_id_field'

export interface FunnelDataWarehouseStepDefinitionPopoverLogicProps {
    table: DataWarehouseTableForInsight
    taxonomicFilterLogicKey: string
    insightProps: InsightLogicProps
}

export const funnelDataWarehouseStepDefinitionPopoverLogic = kea([
    props({} as FunnelDataWarehouseStepDefinitionPopoverLogicProps),
    key(
        (props) =>
            `${props.table.name}_${props.taxonomicFilterLogicKey}_${keyForInsightLogicProps('new')(props.insightProps)}`
    ),
    path((key) => ['scenes', 'insights', 'EditorFilters', 'funnelDataWarehouseStepDefinitionPopoverLogic', key]),
    connect((props) => ({
        values: [
            taxonomicFilterLogic({ taxonomicFilterLogicKey: props.taxonomicFilterLogicKey }),
            ['dataWarehousePopoverFields'],
            definitionPopoverLogic,
            ['localDefinition'],
            funnelDataLogic(props.insightProps),
            ['querySource'],
        ],
        actions: [
            taxonomicFilterLogic({ taxonomicFilterLogicKey: props.taxonomicFilterLogicKey }),
            ['selectItem'],
            definitionPopoverLogic,
            ['setLocalDefinition'],
        ],
    })),
    actions(() => ({
        setActiveFieldKey: (activeFieldKey: FunnelFieldKey) => ({ activeFieldKey }),
    })),
    reducers({
        activeFieldKey: [
            'id_field' as FunnelFieldKey,
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
        isAggregatingByGroup: [
            (s) => [s.querySource, s.activeFieldKey],
            (querySource, activeFieldKey) =>
                querySource?.aggregation_group_type_index !== undefined &&
                querySource?.aggregation_group_type_index !== null,
        ],
        isAggregatingByHogQL: [
            (s) => [s.querySource, s.isGroupAggregationTarget],
            (querySource, isGroupAggregationTarget) =>
                Boolean(querySource?.funnelsFilter?.funnelAggregateByHogQL) && !isGroupAggregationTarget,
        ],
    }),
])
