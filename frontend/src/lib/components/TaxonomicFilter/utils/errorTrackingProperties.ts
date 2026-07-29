import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

const EXCEPTION_PROPERTY_CAPABILITIES: Record<
    string,
    { curated: boolean; searchable: boolean; internal: boolean; filterable: boolean }
> = {
    $exception_types: { curated: true, searchable: true, internal: true, filterable: true },
    $exception_values: { curated: true, searchable: true, internal: true, filterable: true },
    $exception_sources: { curated: true, searchable: true, internal: true, filterable: true },
    $exception_functions: { curated: true, searchable: true, internal: true, filterable: true },
    $exception_handled: { curated: true, searchable: false, internal: false, filterable: true },
    $exception_steps: { curated: false, searchable: false, internal: false, filterable: false },
    $exception_list: { curated: false, searchable: false, internal: true, filterable: false },
    $exception_fingerprint_record: { curated: false, searchable: false, internal: true, filterable: false },
    $exception_proposed_fingerprint: { curated: false, searchable: false, internal: true, filterable: true },
}

function exceptionPropertiesWith(capability: keyof (typeof EXCEPTION_PROPERTY_CAPABILITIES)[string]): string[] {
    return Object.entries(EXCEPTION_PROPERTY_CAPABILITIES)
        .filter(([, capabilities]) => capabilities[capability])
        .map(([property]) => property)
}

export const SEARCHABLE_EXCEPTION_PROPERTIES = exceptionPropertiesWith('searchable')
export const INTERNAL_EXCEPTION_PROPERTY_KEYS = exceptionPropertiesWith('internal')

export function getCuratedExceptionPropertyOptions(): string[] {
    return exceptionPropertiesWith('curated')
}

export function getNonFilterableExceptionProperties(): string[] {
    return Object.entries(EXCEPTION_PROPERTY_CAPABILITIES)
        .filter(([, capabilities]) => !capabilities.filterable)
        .map(([property]) => property)
}

function isFilterableExceptionProperty(property: unknown): boolean {
    return typeof property !== 'string' || EXCEPTION_PROPERTY_CAPABILITIES[property]?.filterable !== false
}

export function isFilterableExceptionPropertyForGroup(groupType: TaxonomicFilterGroupType, property: unknown): boolean {
    return (
        (groupType !== TaxonomicFilterGroupType.EventProperties &&
            groupType !== TaxonomicFilterGroupType.ExceptionProperties) ||
        isFilterableExceptionProperty(property)
    )
}

export function getCuratedExceptionPropertyExclusions(
    requestedGroupTypes: TaxonomicFilterGroupType[] | undefined
): string[] {
    return requestedGroupTypes?.includes(TaxonomicFilterGroupType.ExceptionProperties)
        ? getCuratedExceptionPropertyOptions()
        : []
}
