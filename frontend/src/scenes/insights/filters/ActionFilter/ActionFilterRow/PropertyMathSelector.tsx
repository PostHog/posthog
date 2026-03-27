import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'

interface PropertyMathSelectorProps {
    mathPropertyType: TaxonomicFilterGroupType | null | undefined
    mathProperty: string | null | undefined
    mathName: string | null | undefined
    index: number
    onMathPropertySelect: (index: number, value: string, groupType: TaxonomicFilterGroupType) => void
    showNumericalPropsOnly?: boolean
    schemaColumns: DatabaseSchemaField[]
    /** Display name of the math aggregation, e.g. "average" */
    mathDisplayName?: string
}

type BoxPlotPropertySelectorProps = Pick<
    PropertyMathSelectorProps,
    'mathPropertyType' | 'mathProperty' | 'index' | 'onMathPropertySelect' | 'mathName'
>

export function BoxPlotPropertySelector({
    mathPropertyType,
    mathProperty,
    index,
    onMathPropertySelect,
    mathName,
}: BoxPlotPropertySelectorProps): JSX.Element {
    return (
        <div className="flex-auto min-w-0">
            <TaxonomicStringPopover
                groupType={mathPropertyType || TaxonomicFilterGroupType.NumericalEventProperties}
                groupTypes={[
                    TaxonomicFilterGroupType.NumericalEventProperties,
                    TaxonomicFilterGroupType.SessionProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                ]}
                value={mathProperty || undefined}
                onChange={(currentValue, groupType) => onMathPropertySelect(index, currentValue, groupType)}
                eventNames={mathName ? [mathName] : []}
                placeholder="Select numeric property"
                data-attr="box-plot-property-select"
                showNumericalPropsOnly
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

export function PropertyValueMathSelector({
    mathPropertyType,
    mathProperty,
    mathName,
    index,
    onMathPropertySelect,
    showNumericalPropsOnly,
    schemaColumns,
    mathDisplayName,
}: PropertyMathSelectorProps): JSX.Element {
    return (
        <div className="flex-auto min-w-0">
            <TaxonomicStringPopover
                groupType={mathPropertyType || TaxonomicFilterGroupType.NumericalEventProperties}
                groupTypes={[
                    TaxonomicFilterGroupType.DataWarehouseProperties,
                    TaxonomicFilterGroupType.NumericalEventProperties,
                    TaxonomicFilterGroupType.SessionProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.DataWarehousePersonProperties,
                ]}
                schemaColumns={schemaColumns}
                value={mathProperty}
                onChange={(currentValue, groupType) => onMathPropertySelect(index, currentValue, groupType)}
                eventNames={mathName ? [mathName] : []}
                data-attr="math-property-select"
                showNumericalPropsOnly={showNumericalPropsOnly}
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
