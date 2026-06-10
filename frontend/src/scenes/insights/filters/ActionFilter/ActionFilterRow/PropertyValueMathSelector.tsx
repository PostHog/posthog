import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'

interface PropertyValueMathSelectorProps {
    /** The currently selected taxonomic group for the math property, e.g. session or person properties. */
    mathPropertyType: TaxonomicFilterGroupType | null | undefined
    /** The set of taxonomic groups the picker should allow the user to choose math properties from. */
    mathPropertyTypes: TaxonomicFilterGroupType[] | null | undefined
    /** The currently selected property key to aggregate over for property-value math. */
    mathProperty: string | null | undefined
    /** The event or action name used to scope property suggestions shown in the picker. */
    mathName: string | null | undefined
    /** The row index used when reporting selection changes back to the parent filter list. */
    index: number
    /** Called when the user selects a property and its taxonomic group. */
    onMathPropertySelect: (index: number, value: string, groupType: TaxonomicFilterGroupType) => void
    showNumericalPropsOnly?: boolean
    /** Available schema fields for data warehouse property suggestions when the picker is scoped to a table. */
    schemaColumns: DatabaseSchemaField[]
    /** Display name of the math aggregation, e.g. "average" */
    mathDisplayName?: string
}

export function PropertyValueMathSelector({
    mathPropertyType,
    mathPropertyTypes,
    mathProperty,
    mathName,
    index,
    onMathPropertySelect,
    showNumericalPropsOnly,
    schemaColumns,
    mathDisplayName,
}: PropertyValueMathSelectorProps): JSX.Element {
    return (
        <div className="flex-auto min-w-0">
            <TaxonomicStringPopover
                groupType={mathPropertyType || TaxonomicFilterGroupType.NumericalEventProperties}
                groupTypes={
                    mathPropertyTypes || [
                        TaxonomicFilterGroupType.NumericalEventProperties,
                        TaxonomicFilterGroupType.SessionProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.DataWarehousePersonProperties,
                        TaxonomicFilterGroupType.DataWarehouseProperties,
                    ]
                }
                schemaColumns={schemaColumns}
                value={mathProperty}
                onChange={(currentValue, groupType) => onMathPropertySelect(index, currentValue, groupType)}
                eventNames={mathName ? [mathName] : []}
                data-attr="math-property-select"
                showNumericalPropsOnly={showNumericalPropsOnly}
                selectingKeyOnly
                renderValue={(currentValue) => (
                    <Tooltip
                        title={
                            currentValue === '$session_duration' ? (
                                <>
                                    Calculate {mathDisplayName} of the session duration. This is based on the{' '}
                                    <code>$session_id</code> property associated with events. The duration is derived
                                    from the time difference between the first and last event for each distinct{' '}
                                    <code>$session_id</code>.
                                </>
                            ) : (
                                <>
                                    Calculate {mathDisplayName} from property <code>{currentValue}</code>. Note that
                                    only {mathName} occurrences where <code>{currentValue}</code> is set with a numeric
                                    value will be taken into account.
                                </>
                            )
                        }
                        placement="right"
                    >
                        <PropertyKeyInfo
                            value={currentValue}
                            disablePopover
                            type={TaxonomicFilterGroupType.EventProperties}
                        />
                    </Tooltip>
                )}
            />
        </div>
    )
}
