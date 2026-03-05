import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import type { TaxonomicFilterGroup } from 'lib/components/TaxonomicFilter/types'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightLogicProps } from '~/types'

import type { funnelDataWarehouseStepDefinitionPopoverLogicType } from './funnelDataWarehouseStepDefinitionPopoverLogicType'

export type FunnelFieldKey = 'id_field' | 'timestamp_field' | 'distinct_id_field'

export interface FunnelDataWarehouseStepDefinitionPopoverLogicProps {
    table: DataWarehouseTableForInsight
    group: TaxonomicFilterGroup
    taxonomicFilterLogicKey: string
    insightProps: InsightLogicProps
}

export const funnelDataWarehouseStepDefinitionPopoverLogic = kea<funnelDataWarehouseStepDefinitionPopoverLogicType>([
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
        selectTable: true,
    })),
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
    listeners(({ actions, values, props }) => ({
        selectTable: () => {
            actions.selectItem(props.group, props.table.name, values.localDefinition)
        },
    })),
])
