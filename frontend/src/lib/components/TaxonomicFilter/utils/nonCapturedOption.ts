import { TaxonomicFilterGroupType } from '../types'

export type NonCapturedKind = 'event' | 'property'

const EVENT_GROUP_TYPES = new Set<TaxonomicFilterGroupType>([
    TaxonomicFilterGroupType.Events,
    TaxonomicFilterGroupType.CustomEvents,
])

const PROPERTY_GROUP_TYPES = new Set<TaxonomicFilterGroupType>([
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
])

/**
 * Which "not seen yet" row a group can offer, or null when the group offers none.
 * Only keys a project defines by sending them qualify — a fixed schema (event metadata,
 * warehouse columns) cannot gain a key the user types.
 */
export function nonCapturedKindForGroup(
    groupType: TaxonomicFilterGroupType,
    allowNonCapturedEvents: boolean,
    allowNonCapturedProperties: boolean
): NonCapturedKind | null {
    if (allowNonCapturedEvents && EVENT_GROUP_TYPES.has(groupType)) {
        return 'event'
    }
    if (
        allowNonCapturedProperties &&
        (PROPERTY_GROUP_TYPES.has(groupType) || groupType.startsWith(TaxonomicFilterGroupType.GroupsPrefix))
    ) {
        return 'property'
    }
    return null
}
