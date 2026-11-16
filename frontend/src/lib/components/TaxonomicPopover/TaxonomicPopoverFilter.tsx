import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'

import type { TaxonomicPopoverProps } from './TaxonomicPopover'

export type TaxonomicPopoverFilterProps<ValueType extends TaxonomicFilterValue = TaxonomicFilterValue> = Pick<
    TaxonomicPopoverProps<ValueType>,
    | 'groupType'
    | 'value'
    | 'filter'
    | 'groupTypes'
    | 'eventNames'
    | 'schemaColumns'
    | 'metadataSource'
    | 'excludedProperties'
    | 'excludedOperators'
    | 'includeHiddenEvents'
    | 'offerHiddenEventStandIns'
    | 'selectedProperties'
    | 'showNumericalPropsOnly'
    | 'dataWarehousePopoverFields'
    | 'maxContextOptions'
    | 'allowNonCapturedEvents'
    | 'definitionPopoverRenderer'
    | 'suggestedFiltersLabel'
    | 'enableKeywordShortcuts'
    | 'promoteSelectedItemToFirstPosition'
    | 'selectingKeyOnly'
    | 'width'
> & {
    taxonomicFilterLogicKey: string
    onSelect: (value: ValueType, groupType: TaxonomicFilterGroupType, item: any) => void
}

export function TaxonomicPopoverFilter<ValueType extends TaxonomicFilterValue = TaxonomicFilterValue>({
    taxonomicFilterLogicKey,
    onSelect,
    groupType,
    groupTypes,
    eventNames = [],
    ...rest
}: TaxonomicPopoverFilterProps<ValueType>): JSX.Element {
    return (
        <TaxonomicFilter
            {...rest}
            taxonomicFilterLogicKey={taxonomicFilterLogicKey}
            groupType={groupType}
            onChange={({ type }, payload, item) => onSelect(payload as ValueType, type, item)}
            taxonomicGroupTypes={groupTypes ?? [groupType]}
            eventNames={eventNames}
        />
    )
}
