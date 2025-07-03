import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { ConversionGoalFilter } from '~/queries/schema/schema-general'
import { conversionGoalPopoverFields } from '~/taxonomy/taxonomy'
import { BaseMathType, EntityTypes, FilterType, PropertyMathType } from '~/types'

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
            value.kind === 'EventsNode'
                ? [
                      {
                          ...value,
                          type: 'events',
                          id: value.event || '',
                          math: value.math || BaseMathType.TotalCount,
                      },
                  ]
                : [],
        actions:
            value.kind === 'ActionsNode'
                ? [
                      {
                          ...value,
                          type: 'actions',
                          id: (value as any).id || '',
                          math: value.math || BaseMathType.TotalCount,
                      },
                  ]
                : [],
        data_warehouse:
            value.kind === 'DataWarehouseNode'
                ? [
                      {
                          ...value,
                          type: 'data_warehouse',
                          id: (value as any).table_name || '',
                          math: value.math || BaseMathType.TotalCount,
                      },
                  ]
                : [],
    }

    return (
        <ActionFilter
            bordered
            allowedMathTypes={[BaseMathType.TotalCount, BaseMathType.UniqueUsers, PropertyMathType.Sum]}
            filters={currentFilter}
            mathAvailability={MathAvailability.All}
            setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                const series = actionsAndEventsToSeries(
                    { actions, events, data_warehouse } as any,
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
                        ...(firstSerie as any).schema,
                    },
                }

                // Override the schema with the schema from the data warehouse
                if (data_warehouse?.[0]?.type === EntityTypes.DATA_WAREHOUSE) {
                    const schema = data_warehouse[0] as unknown as Record<ConversionGoalSchema, string>
                    const overrideSchema: Record<ConversionGoalSchema, string> = {
                        utm_campaign_name: schema[UTM_CAMPAIGN_NAME_SCHEMA_FIELD],
                        utm_source_name: schema[UTM_SOURCE_NAME_SCHEMA_FIELD],
                        timestamp_field: schema[TIMESTAMP_FIELD_SCHEMA_FIELD],
                        distinct_id_field: schema[DISTINCT_ID_FIELD_SCHEMA_FIELD],
                    }
                    newFilter.schema_map = overrideSchema
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
