import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

// People type a category's name to browse it, and no item is called "person" or "events".
const GROUP_TYPE_BY_TYPED_NAME: Record<string, TaxonomicFilterGroupType> = {
    person: TaxonomicFilterGroupType.PersonProperties,
    persons: TaxonomicFilterGroupType.PersonProperties,
    people: TaxonomicFilterGroupType.PersonProperties,
    user: TaxonomicFilterGroupType.PersonProperties,
    users: TaxonomicFilterGroupType.PersonProperties,
    event: TaxonomicFilterGroupType.Events,
    events: TaxonomicFilterGroupType.Events,
    cohort: TaxonomicFilterGroupType.Cohorts,
    cohorts: TaxonomicFilterGroupType.Cohorts,
    action: TaxonomicFilterGroupType.Actions,
    actions: TaxonomicFilterGroupType.Actions,
    session: TaxonomicFilterGroupType.SessionProperties,
    sessions: TaxonomicFilterGroupType.SessionProperties,
    flag: TaxonomicFilterGroupType.FeatureFlags,
    flags: TaxonomicFilterGroupType.FeatureFlags,
    'feature flag': TaxonomicFilterGroupType.FeatureFlags,
    'feature flags': TaxonomicFilterGroupType.FeatureFlags,
}

/** The category a search names, when the picker offers that category. */
export function groupNamedBySearch(
    searchQuery: string,
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
): TaxonomicFilterGroupType | null {
    const groupType = GROUP_TYPE_BY_TYPED_NAME[searchQuery.trim().toLowerCase()]
    return groupType && taxonomicGroupTypes.includes(groupType) ? groupType : null
}
