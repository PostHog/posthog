import { PropertyGroupFilter, AnyPropertyFilter, EventDefinition, PropertyFilter, PropertyOperator } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { flattenPropertyGroup, isPropertyGroup } from 'lib/utils'

export function parseProperties(
    input: AnyPropertyFilter[] | PropertyGroupFilter | Record<string, string> | null | undefined
): AnyPropertyFilter[] {
    if (Array.isArray(input) || !input) {
        return input || []
    }
    if (input && !Array.isArray(input) && isPropertyGroup(input)) {
        return flattenPropertyGroup([], input as PropertyGroupFilter)
    }
    // Old style dict properties
    return Object.entries(input).map(([inputKey, value]) => {
        const [key, operator] = inputKey.split('__')
        return {
            key,
            value,
            operator: operator as PropertyOperator,
            type: 'event',
        }
    })
}

/** Checks if the AnyPropertyFilter is a filled PropertyFilter */
export function isValidPropertyFilter(filter: AnyPropertyFilter): filter is PropertyFilter {
    return (
        !!filter && // is not falsy
        'key' in filter && // has a "key" property
        Object.values(filter).some((v) => !!v) // contains some properties with values
    )
}

export function isValidPathCleanFilter(filter: Record<string, any>): boolean {
    return filter.alias && filter.regex
}

export function filterMatchesItem(
    filter?: AnyPropertyFilter | null,
    item?: EventDefinition | null,
    itemType?: string
): boolean {
    if (!filter || !item || !itemType || filter.type !== itemType) {
        return false
    }
    return filter.type === 'cohort' ? filter.value === item.id : filter.key === item.name
}

const propertyFilterMapping: Record<string, TaxonomicFilterGroupType> = {
    person: TaxonomicFilterGroupType.PersonProperties,
    event: TaxonomicFilterGroupType.EventProperties,
    feature: TaxonomicFilterGroupType.EventFeatureFlags,
    cohort: TaxonomicFilterGroupType.Cohorts,
    element: TaxonomicFilterGroupType.Elements,
    session: TaxonomicFilterGroupType.Sessions,
}

export function propertyFilterTypeToTaxonomicFilterType(
    filterType?: string | null,
    groupTypeIndex?: number | null
): TaxonomicFilterGroupType | undefined {
    if (!filterType) {
        return undefined
    }
    if (filterType == 'group') {
        return `${TaxonomicFilterGroupType.GroupsPrefix}_${groupTypeIndex}` as TaxonomicFilterGroupType
    }
    return propertyFilterMapping[filterType]
}

export function taxonomicFilterTypeToPropertyFilterType(filterType?: TaxonomicFilterGroupType): string | undefined {
    if (filterType === TaxonomicFilterGroupType.CohortsWithAllUsers) {
        return 'cohort'
    }
    if (filterType?.startsWith(TaxonomicFilterGroupType.GroupsPrefix)) {
        return 'group'
    }
    return Object.entries(propertyFilterMapping).find(([, v]) => v === filterType)?.[0]
}
