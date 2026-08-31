import { IconPlusSmall } from '@posthog/icons'

import { newBehavioralFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { BehavioralPropertyFilter } from '~/types'

export interface AddBehavioralFilterButtonProps {
    onAdd: (filter: BehavioralPropertyFilter) => void
    'data-attr': string
}

export function AddBehavioralFilterButton({
    onAdd,
    'data-attr': dataAttr,
}: AddBehavioralFilterButtonProps): JSX.Element {
    return (
        <TaxonomicPopover
            groupType={TaxonomicFilterGroupType.Events}
            groupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
            value={null}
            onChange={(value, groupType) =>
                onAdd(
                    newBehavioralFilter(
                        String(value),
                        groupType === TaxonomicFilterGroupType.Actions ? 'actions' : 'events'
                    )
                )
            }
            placeholder="Performed"
            placeholderClass=""
            icon={<IconPlusSmall />}
            sideIcon={null}
            data-attr={dataAttr}
        />
    )
}
