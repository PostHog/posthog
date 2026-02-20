import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'

import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    DataWarehousePopoverField,
    DefinitionPopoverRendererProps,
    TaxonomicDefinitionTypes,
} from 'lib/components/TaxonomicFilter/types'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'

import type { funnelDataWarehouseStepDefinitionPopoverLogicType } from './funnelDataWarehouseStepDefinitionPopoverLogicType'

export interface FunnelDataWarehouseStepDefinitionPopoverLogicProps {
    item: DefinitionPopoverRendererProps['item']
    group: DefinitionPopoverRendererProps['group']
}

type LocalDefinition = Partial<TaxonomicDefinitionTypes> & Record<string, any>
type DataWarehouseField = DataWarehouseTableForInsight['fields'][string]

export interface DataWarehouseColumnOption {
    label: string
    value: string
    type: string
}

const HOGQL_OPTION = { label: 'SQL Expression', value: '' }

export const funnelDataWarehouseStepDefinitionPopoverLogic = kea<funnelDataWarehouseStepDefinitionPopoverLogicType>([
    path(['scenes', 'insights', 'EditorFilters', 'funnelDataWarehouseStepDefinitionPopoverLogic']),
    props({} as FunnelDataWarehouseStepDefinitionPopoverLogicProps),
    key((props) => `${props.group.type}-${String(props.group.getValue?.(props.item) ?? props.item.name ?? 'new')}`),
    connect({
        values: [
            definitionPopoverLogic,
            ['localDefinition'],
            taxonomicFilterLogic,
            ['dataWarehousePopoverFields as rawDataWarehousePopoverFields'],
        ],
        actions: [definitionPopoverLogic, ['setLocalDefinition'], taxonomicFilterLogic, ['selectItem']],
    }),
    actions(() => ({
        setFieldValue: (fieldKey: unknown, value: unknown) => ({ fieldKey, value }),
        selectDataWarehouseStep: true,
    })),
    selectors({
        dataWarehousePopoverFields: [
            (s) => [s.rawDataWarehousePopoverFields],
            (dataWarehousePopoverFields: unknown): DataWarehousePopoverField[] =>
                Array.isArray(dataWarehousePopoverFields) ? dataWarehousePopoverFields : [],
        ],
        definition: [
            (s) => [s.localDefinition, (_, props) => props.item],
            (
                localDefinition: LocalDefinition,
                item: DefinitionPopoverRendererProps['item']
            ): DataWarehouseTableForInsight | null => {
                if ('fields' in localDefinition) {
                    return localDefinition as DataWarehouseTableForInsight
                }
                if ('fields' in item) {
                    return item as DataWarehouseTableForInsight
                }
                return null
            },
        ],
        columnOptions: [
            (s) => [s.definition],
            (definition: DataWarehouseTableForInsight | null): DataWarehouseColumnOption[] =>
                Object.values(definition?.fields ?? {}).map((column: DataWarehouseField) => ({
                    label: `${column.name} (${column.type})`,
                    value: column.name,
                    type: column.type,
                })),
        ],
        hogQLOption: [() => [], () => HOGQL_OPTION],
        itemValue: [
            (s) => [s.localDefinition, (_, props) => props.group],
            (localDefinition: LocalDefinition, group: DefinitionPopoverRendererProps['group']) =>
                localDefinition ? group?.getValue?.(localDefinition) : null,
        ],
        selectionDisabledReason: [
            (s) => [s.dataWarehousePopoverFields, s.localDefinition],
            (dataWarehousePopoverFields: DataWarehousePopoverField[], localDefinition: LocalDefinition) =>
                dataWarehousePopoverFields.every(
                    ({ key, optional }: DataWarehousePopoverField) =>
                        optional || (key in localDefinition && localDefinition[key])
                )
                    ? null
                    : 'All required field mappings must be specified',
        ],
        isUsingHogQLExpression: [
            (s) => [s.definition],
            (definition: DataWarehouseTableForInsight | null) =>
                (value: string | undefined): boolean => {
                    if (value === undefined) {
                        return false
                    }
                    const column = Object.values(definition?.fields ?? {}).find(
                        (field: DataWarehouseField) => field.name === value
                    )
                    return !column
                },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        setFieldValue: ({ fieldKey, value }: { fieldKey: unknown; value: unknown }) => {
            if (typeof fieldKey !== 'string' || (typeof value !== 'string' && value !== null)) {
                return
            }
            actions.setLocalDefinition({ [fieldKey]: value })
        },
        selectDataWarehouseStep: () => {
            actions.selectItem(props.group, values.itemValue ?? null, values.localDefinition, undefined)
        },
    })),
])
