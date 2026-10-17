import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

const PERSON_GROUPS = [TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.Persons]
const FLAG_GROUPS = [TaxonomicFilterGroupType.EventFeatureFlags, TaxonomicFilterGroupType.FeatureFlags]
const COHORT_GROUPS = [TaxonomicFilterGroupType.Cohorts, TaxonomicFilterGroupType.CohortsWithAllUsers]

// Pickers offer the same category under different group types, so each name lists them in order of preference.
const GROUP_TYPES_BY_TYPED_NAME: Record<string, TaxonomicFilterGroupType[]> = {
    person: PERSON_GROUPS,
    persons: PERSON_GROUPS,
    people: PERSON_GROUPS,
    user: PERSON_GROUPS,
    users: PERSON_GROUPS,
    event: [TaxonomicFilterGroupType.Events],
    events: [TaxonomicFilterGroupType.Events],
    cohort: COHORT_GROUPS,
    cohorts: COHORT_GROUPS,
    action: [TaxonomicFilterGroupType.Actions],
    actions: [TaxonomicFilterGroupType.Actions],
    session: [TaxonomicFilterGroupType.SessionProperties],
    sessions: [TaxonomicFilterGroupType.SessionProperties],
    flag: FLAG_GROUPS,
    flags: FLAG_GROUPS,
    'feature flag': FLAG_GROUPS,
    'feature flags': FLAG_GROUPS,
}

/**
 * The category a search names, when the picker offers it. The empty state calls this only after the
 * search found nothing, so a search for a category's name is taken as a request to browse that category.
 */
export function groupNamedBySearch(
    searchQuery: string,
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
): TaxonomicFilterGroupType | null {
    const candidates = GROUP_TYPES_BY_TYPED_NAME[searchQuery.trim().toLowerCase()] ?? []
    return candidates.find((groupType) => taxonomicGroupTypes.includes(groupType)) ?? null
}
