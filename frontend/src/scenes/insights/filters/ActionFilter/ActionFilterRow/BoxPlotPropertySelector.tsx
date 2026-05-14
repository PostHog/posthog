import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

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
}

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
