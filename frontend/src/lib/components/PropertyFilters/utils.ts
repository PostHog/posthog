import { AnyPropertyFilter, EventDefinition, PropertyFilter, PropertyOperator } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export function parseProperties(
    input: AnyPropertyFilter[] | Record<string, string> | null | undefined
): AnyPropertyFilter[] {
    if (Array.isArray(input) || !input) {
        return input || []
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
    cohort: TaxonomicFilterGroupType.Cohorts,
    element: TaxonomicFilterGroupType.Elements,
    groups: TaxonomicFilterGroupType.Groups,
}

export function propertyFilterTypeToTaxonomicFilterType(
    filterType?: string | null
): TaxonomicFilterGroupType | undefined {
    return filterType && filterType in propertyFilterMapping ? propertyFilterMapping[filterType] : undefined
}

export function taxonomicFilterTypeToPropertyFilterType(filterType?: TaxonomicFilterGroupType): string | undefined {
    if (filterType === TaxonomicFilterGroupType.CohortsWithAllUsers) {
        return 'cohort'
    }
    return Object.entries(propertyFilterMapping).find(([, v]) => v === filterType)?.[0]
}
