import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { isAllEventsEntityFilter } from 'scenes/insights/utils'

import { ActionFilter, EntityType, EntityTypes } from '~/types'

export const getValue = (
    value: string | number | null | undefined,
    filter: ActionFilter
): string | number | null | undefined => {
    if (isAllEventsEntityFilter(filter)) {
        return 'All events'
    } else if (filter.type === 'actions') {
        return typeof value === 'string' ? parseInt(value) : value || undefined
    }
    return value === null ? null : value || undefined
}

const taxonomicFilterGroupTypeToEntityTypeMapping: Partial<Record<TaxonomicFilterGroupType, EntityTypes>> = {
    [TaxonomicFilterGroupType.Events]: EntityTypes.EVENTS,
    [TaxonomicFilterGroupType.Actions]: EntityTypes.ACTIONS,
    [TaxonomicFilterGroupType.DataWarehouse]: EntityTypes.DATA_WAREHOUSE,
}

export function taxonomicFilterGroupTypeToEntityType(
    taxonomicFilterGroupType: TaxonomicFilterGroupType
): EntityType | null {
    return taxonomicFilterGroupTypeToEntityTypeMapping[taxonomicFilterGroupType] || null
}
