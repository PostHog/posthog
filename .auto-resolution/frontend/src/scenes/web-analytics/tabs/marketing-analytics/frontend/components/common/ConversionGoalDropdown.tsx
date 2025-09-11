import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter as ActionFilterComponent } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import {
    ActionsNode,
    ConversionGoalFilter,
    DataWarehouseNode,
    EventsNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import { isDataWarehouseNode } from '~/queries/utils'
import { conversionGoalPopoverFields } from '~/taxonomy/taxonomy'
import { ActionFilter, BaseMathType, DataWarehouseFilter, EntityTypes, FilterType, PropertyMathType } from '~/types'

import {
    ConversionGoalSchema,
    DISTINCT_ID_FIELD_SCHEMA_FIELD,
    TIMESTAMP_FIELD_SCHEMA_FIELD,
    UTM_CAMPAIGN_NAME_SCHEMA_FIELD,
    UTM_SOURCE_NAME_SCHEMA_FIELD,
} from '../../../utils'

interface ConversionGoalDropdownProps {
    value: ConversionGoalFilter
    onChange: (filter: ConversionGoalFilter) => void
    typeKey: string
}

export function ConversionGoalDropdown({ value, onChange, typeKey }: ConversionGoalDropdownProps): JSX.Element {
    // Create a proper ActionFilter-compatible filter object
    const currentFilter = {
        events:
            value.kind === NodeKind.EventsNode && !hasDataWarehouseType(value)
                ? [
                      {
                          ...value,
                          type: 'events',
                          id: (value as EventsNode).event || '',
                          math: value.math || BaseMathType.TotalCount,
                      },
                  ]
                : [],
        actions:
            value.kind === NodeKind.ActionsNode
                ? [
                      {
                          ...value,
                          type: 'actions',
                          id: (value as ActionsNode).id || '',
                          math: value.math || BaseMathType.TotalCount,
                      },
                  ]
                : [],
        data_warehouse:
            value.kind === NodeKind.DataWarehouseNode || hasDataWarehouseType(value)
                ? [
                      {
                          ...value,
                          type: 'data_warehouse',
                          id: isDataWarehouseNode(value) ? value.table_name : (value as any).table_name || '',
                          math: value.math || BaseMathType.TotalCount,
                      },
                  ]
                : [],
    }

    return (
        <ActionFilterComponent
            bordered
            allowedMathTypes={[BaseMathType.TotalCount, BaseMathType.UniqueUsers, PropertyMathType.Sum]}
            filters={currentFilter}
            mathAvailability={MathAvailability.All}
            setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                const series = actionsAndEventsToSeries(
                    {
                        actions: actions as ActionFilter[] | undefined,
                        events: events as ActionFilter[] | undefined,
                        data_warehouse: data_warehouse as DataWarehouseFilter[] | undefined,
                    },
                    true,
                    MathAvailability.All
                )

                const firstSerie = series[0] || value

                const newFilter: ConversionGoalFilter = {
                    ...value,
                    ...firstSerie,
                    // Preserve the existing schema to keep UTM mappings
                    schema_map: {
                        ...value.schema_map,
                    },
                    properties: firstSerie?.properties || [], // if we clear the filter we need the properties to be set to an empty array
                }

                // Override the schema with the schema from the data warehouse
                if (data_warehouse?.[0]?.type === EntityTypes.DATA_WAREHOUSE) {
                    const dwNode = data_warehouse[0] as DataWarehouseFilter & Record<ConversionGoalSchema, string>
                    const schema = dwNode
                    const overrideSchema: Record<ConversionGoalSchema, string> = {
                        utm_campaign_name: schema[UTM_CAMPAIGN_NAME_SCHEMA_FIELD],
                        utm_source_name: schema[UTM_SOURCE_NAME_SCHEMA_FIELD],
                        timestamp_field: schema[TIMESTAMP_FIELD_SCHEMA_FIELD],
                        distinct_id_field: schema[DISTINCT_ID_FIELD_SCHEMA_FIELD],
                    }
                    newFilter.schema_map = overrideSchema

                    // Cast to DataWarehouseNode for type safety
                    const dwFilter = newFilter as DataWarehouseNode & ConversionGoalFilter
                    // Remove the event field that causes validation to fail
                    if ('event' in dwFilter) {
                        delete (dwFilter as any).event
                    }

                    dwFilter.kind = NodeKind.DataWarehouseNode

                    // Set all required ConversionGoalFilter3 fields
                    dwFilter.id = dwNode.table_name || String(dwNode.id) || ''
                    dwFilter.id_field = dwNode.id_field || schema[DISTINCT_ID_FIELD_SCHEMA_FIELD] || 'id'
                    dwFilter.distinct_id_field =
                        dwNode.distinct_id_field || schema[DISTINCT_ID_FIELD_SCHEMA_FIELD] || 'distinct_id'
                    dwFilter.table_name = dwNode.table_name || ''
                    dwFilter.timestamp_field =
                        dwNode.timestamp_field || schema[TIMESTAMP_FIELD_SCHEMA_FIELD] || 'timestamp'
                    dwFilter.dw_source_type = dwNode.dw_source_type
                }
                onChange(newFilter)
            }}
            typeKey={typeKey}
            showSeriesIndicator={false}
            entitiesLimit={1}
            showNumericalPropsOnly={true}
            hideRename={true}
            actionsTaxonomicGroupTypes={[
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.Actions,
                TaxonomicFilterGroupType.DataWarehouse,
            ]}
            dataWarehousePopoverFields={conversionGoalPopoverFields}
        />
    )
}

// Helper function to check if value has data warehouse type field
function hasDataWarehouseType(val: ConversionGoalFilter): boolean {
    return 'type' in val && (val as any).type === 'data_warehouse'
}
