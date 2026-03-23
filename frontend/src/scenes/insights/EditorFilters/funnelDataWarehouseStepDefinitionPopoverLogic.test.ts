import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import type { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'

import type { DatabaseSchemaField } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { funnelDataWarehouseStepDefinitionPopoverLogic } from './funnelDataWarehouseStepDefinitionPopoverLogic'

const createField = (name: string, type: DatabaseSchemaField['type']): DatabaseSchemaField => ({
    name,
    hogql_value: name,
    type,
    schema_valid: true,
})

describe('funnelDataWarehouseStepDefinitionPopoverLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('ignores stale field mappings from a previously hovered table', () => {
        const selectedItemMeta: Partial<DataWarehouseTableForInsight> & { table_name: string } = {
            id: 'warehouse_table_a',
            table_name: 'warehouse_table_a',
            timestamp_field: 'date_day',
            id_field: 'id',
            aggregation_target_field: 'person_id',
        }

        const previouslyHoveredTable = {
            id: 'table-a-id',
            name: 'warehouse_table_a',
            type: 'data_warehouse' as const,
            format: 'Parquet',
            url_pattern: '',
            fields: {
                id: createField('id', 'integer'),
                created_at: createField('created_at', 'datetime'),
            },
        } satisfies DataWarehouseTableForInsight

        const currentlyHoveredTable = {
            id: 'table-b-id',
            name: 'warehouse_table_b',
            type: 'data_warehouse' as const,
            format: 'Parquet',
            url_pattern: '',
            fields: {
                id: createField('id', 'integer'),
                event_timestamp: createField('event_timestamp', 'datetime'),
            },
        } satisfies DataWarehouseTableForInsight

        const popoverDefinitionLogic = definitionPopoverLogic.build({
            type: TaxonomicFilterGroupType.DataWarehouse,
            selectedItemMeta,
        })
        popoverDefinitionLogic.mount()
        popoverDefinitionLogic.actions.setDefinition(previouslyHoveredTable)

        expect(
            (popoverDefinitionLogic.values.localDefinition as Partial<DataWarehouseTableForInsight>).timestamp_field
        ).toEqual('date_day')

        const onSelectItem = jest.fn()
        const logic = funnelDataWarehouseStepDefinitionPopoverLogic.build({
            table: currentlyHoveredTable,
            group: { type: TaxonomicFilterGroupType.DataWarehouse } as any,
            dataWarehousePopoverFields: [
                { key: 'id_field', label: 'Unique ID' },
                { key: 'timestamp_field', label: 'Timestamp' },
                { key: 'aggregation_target_field', label: 'Aggregation target', allowHogQL: true },
            ],
            selectedItemMeta,
            onSelectItem,
            insightProps: { dashboardItemId: undefined } as any,
        })
        logic.mount()

        expect(logic.values.previewExpressionColumns).toEqual([])
        expect(logic.values.activeFieldValue).toBeUndefined()

        logic.actions.setActiveFieldKey('timestamp_field')
        expect(logic.values.activeFieldValue).toEqual('event_timestamp')

        logic.actions.selectTable()
        expect(onSelectItem).toHaveBeenCalledWith(
            expect.objectContaining({ type: TaxonomicFilterGroupType.DataWarehouse }),
            'warehouse_table_b',
            expect.objectContaining({
                id_field: 'id',
                timestamp_field: 'event_timestamp',
            })
        )
    })
})
