import { capitalizeFirstLetter } from 'lib/utils/strings'

import { Noun } from '~/models/groupsModel'
import { AnyPropertyFilter, GroupType, PropertyFilterType } from '~/types'

import { FilterBarCategory, FilterBarCategoryId } from './filterBarTypes'

export const STATIC_FILTER_BAR_CATEGORIES: FilterBarCategory[] = [
    {
        id: 'event_properties',
        label: 'Event properties',
        plural: 'event properties',
        propertyFilterType: PropertyFilterType.Event,
        tier: 'primary',
    },
    {
        id: 'person_properties',
        label: 'Person properties',
        plural: 'person properties',
        propertyFilterType: PropertyFilterType.Person,
        tier: 'primary',
    },
    {
        id: 'session_properties',
        label: 'Session properties',
        plural: 'session properties',
        propertyFilterType: PropertyFilterType.Session,
        tier: 'primary',
    },
    {
        id: 'feature_flags',
        label: 'Feature flags',
        plural: 'feature flags',
        propertyFilterType: PropertyFilterType.Event,
        tier: 'primary',
    },
    {
        id: 'cohorts',
        label: 'Cohorts',
        plural: 'cohorts',
        propertyFilterType: PropertyFilterType.Cohort,
        tier: 'primary',
    },
    {
        id: 'elements',
        label: 'Autocapture elements',
        plural: 'element attributes',
        propertyFilterType: PropertyFilterType.Element,
        tier: 'more',
    },
    {
        id: 'sql',
        label: 'SQL expression',
        plural: 'SQL expressions',
        propertyFilterType: PropertyFilterType.HogQL,
        tier: 'more',
    },
]

export function groupPropertiesCategoryId(groupTypeIndex: number): FilterBarCategoryId {
    return `group_properties_${groupTypeIndex}`
}

export function groupPropertiesCategory(groupType: GroupType, noun: Noun): FilterBarCategory {
    return {
        id: groupPropertiesCategoryId(groupType.group_type_index),
        label: `${capitalizeFirstLetter(noun.singular)} properties`,
        plural: `${noun.singular} properties`,
        propertyFilterType: PropertyFilterType.Group,
        groupTypeIndex: groupType.group_type_index,
        tier: 'more',
    }
}

/** The category a stored filter belongs to, or null when the filter bar does not handle its type. */
export function categoryIdForFilter(filter: AnyPropertyFilter): FilterBarCategoryId | null {
    switch (filter.type) {
        case PropertyFilterType.Event:
            return filter.key?.startsWith('$feature/') ? 'feature_flags' : 'event_properties'
        case PropertyFilterType.Person:
            return 'person_properties'
        case PropertyFilterType.Session:
            return 'session_properties'
        case PropertyFilterType.Cohort:
            return 'cohorts'
        case PropertyFilterType.Element:
            return 'elements'
        case PropertyFilterType.HogQL:
            return 'sql'
        case PropertyFilterType.Group:
            return typeof filter.group_type_index === 'number'
                ? groupPropertiesCategoryId(filter.group_type_index)
                : null
        default:
            return null
    }
}
