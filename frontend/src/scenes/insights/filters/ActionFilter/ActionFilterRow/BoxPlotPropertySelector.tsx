import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'

interface BoxPlotPropertySelectorProps {
    /** The currently selected taxonomic group for the box plot property, e.g. session or person properties. */
    mathPropertyType: TaxonomicFilterGroupType | null | undefined
    /** The currently selected numeric property key for the box plot calculation. */
    mathProperty: string | null | undefined
    /** The row index used when reporting selection changes back to the parent filter list. */
    index: number
    /** Called when the user selects a property and its taxonomic group. */
    onMathPropertySelect: (index: number, value: string, groupType: TaxonomicFilterGroupType) => void
    /** The event or action name used to scope property suggestions shown in the picker. */
    mathName: string | null | undefined
    /** Whether the series is a data warehouse table, which scopes the picker to the table's columns. */
    isDataWarehouseFilter?: boolean
    /** Available schema fields for data warehouse column suggestions when the picker is scoped to a table. */
    schemaColumns?: DatabaseSchemaField[]
}

export function BoxPlotPropertySelector({
    mathPropertyType,
    mathProperty,
    index,
    onMathPropertySelect,
    mathName,
    isDataWarehouseFilter,
    schemaColumns,
}: BoxPlotPropertySelectorProps): JSX.Element {
    return (
        <div className="flex-auto min-w-0">
            <TaxonomicStringPopover
                groupType={
                    isDataWarehouseFilter
                        ? TaxonomicFilterGroupType.DataWarehouseProperties
                        : mathPropertyType || TaxonomicFilterGroupType.NumericalEventProperties
                }
                groupTypes={
                    isDataWarehouseFilter
                        ? [TaxonomicFilterGroupType.DataWarehouseProperties]
                        : [
                              TaxonomicFilterGroupType.NumericalEventProperties,
                              TaxonomicFilterGroupType.SessionProperties,
                              TaxonomicFilterGroupType.PersonProperties,
                          ]
                }
                schemaColumns={schemaColumns ?? []}
                value={mathProperty || undefined}
                onChange={(currentValue, groupType) => onMathPropertySelect(index, currentValue, groupType)}
                eventNames={mathName ? [mathName] : []}
                placeholder="Select numeric property"
                data-attr="box-plot-property-select"
                showNumericalPropsOnly
                selectingKeyOnly
                renderValue={(currentValue) => (
                    <PropertyKeyInfo
                        value={currentValue}
                        disablePopover
                        type={TaxonomicFilterGroupType.EventProperties}
                    />
                )}
            />
        </div>
    )
}
