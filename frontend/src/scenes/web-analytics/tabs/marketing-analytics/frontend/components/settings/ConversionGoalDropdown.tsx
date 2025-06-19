import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { ConversionGoalFilter } from '~/queries/schema/schema-general'
import { conversionGoalPopoverFields } from '~/taxonomy/taxonomy'
import { BaseMathType, EntityTypes, FilterType, PropertyMathType } from '~/types'

import { ConversionGoalSchema, UTM_CAMPAIGN_NAME_SCHEMA_FIELD, UTM_SOURCE_NAME_SCHEMA_FIELD } from '../../../utils'

interface ConversionGoalDropdownProps {
    value: ConversionGoalFilter
    onChange: (filter: ConversionGoalFilter) => void
    typeKey: string
}

export function ConversionGoalDropdown({ value, onChange, typeKey }: ConversionGoalDropdownProps): JSX.Element {
    return (
        <ActionFilter
            bordered
            allowedMathTypes={[BaseMathType.TotalCount, BaseMathType.UniqueUsers, PropertyMathType.Sum]}
            filters={{ events: [value] }}
            mathAvailability={MathAvailability.All}
            setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                const series = actionsAndEventsToSeries(
                    { actions, events, data_warehouse } as any,
                    true,
                    MathAvailability.All
                )

                const firstSerie = series[0]

                const newFilter: ConversionGoalFilter = {
                    ...value,
                    ...firstSerie,
                }

                if (data_warehouse?.[0]?.type === EntityTypes.DATA_WAREHOUSE) {
                    const overrideSchema: Record<ConversionGoalSchema, string> = {
                        utm_campaign_name: (data_warehouse[0] as unknown as Record<ConversionGoalSchema, string>)[
                            UTM_CAMPAIGN_NAME_SCHEMA_FIELD
                        ],
                        utm_source_name: (data_warehouse[0] as unknown as Record<ConversionGoalSchema, string>)[
                            UTM_SOURCE_NAME_SCHEMA_FIELD
                        ],
                    }
                    newFilter.schema = overrideSchema
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
