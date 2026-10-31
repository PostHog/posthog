import { BreakdownFilter } from '~/queries/schema/schema-general'
import { BreakdownType } from '~/types'

import { isURLNormalizeable } from 'products/product_analytics/frontend/insights/editor/filters/BreakdownFilter/taxonomicBreakdownFilterUtils'

import { groupPropertiesCategoryId } from './filterBarCategories'
import { fieldLabelForKey, groupTypeIndexForCategory } from './filterBarFields'
import { FilterBarCategoryId, FilterBarField } from './filterBarTypes'

/** Whether a breakdown can split by the fields of this category. Elements and SQL expressions stay filters only. */
export function canBreakDownByCategory(categoryId: FilterBarCategoryId): boolean {
    return categoryId !== 'elements' && categoryId !== 'sql'
}

function breakdownTypeForCategory(categoryId: FilterBarCategoryId): BreakdownType {
    switch (categoryId) {
        case 'person_properties':
            return 'person'
        case 'session_properties':
            return 'session'
        case 'cohorts':
            return 'cohort'
        case 'event_properties':
        case 'feature_flags':
            return 'event'
        default:
            return 'group'
    }
}

export function breakdownForField(field: FilterBarField): BreakdownFilter {
    const breakdownType = breakdownTypeForCategory(field.categoryId)
    return {
        breakdown_type: breakdownType,
        breakdown: breakdownType === 'cohort' ? [Number(field.key)] : field.key,
        breakdown_group_type_index: breakdownType === 'group' ? groupTypeIndexForCategory(field.categoryId) : undefined,
        breakdown_normalize_url: isURLNormalizeable(field.key) ? true : undefined,
    }
}

/**
 * The field a breakdown splits by, or null when there is none. A breakdown saved with the multiple-breakdowns shape
 * reads as its first entry. A cohort breakdown's key is the first cohort id; its label comes from `cohortName`.
 */
export function fieldForBreakdown(
    breakdownFilter: BreakdownFilter | null | undefined,
    cohortName: (id: number) => string | undefined
): FilterBarField | null {
    const first = breakdownFilter?.breakdowns?.[0]
    const type = first ? first.type : breakdownFilter?.breakdown_type
    const rawKey = first ? first.property : breakdownFilter?.breakdown
    const groupTypeIndex = first ? first.group_type_index : breakdownFilter?.breakdown_group_type_index
    const key = Array.isArray(rawKey) ? rawKey[0] : rawKey
    if (key == null || key === '') {
        return null
    }

    let categoryId: FilterBarCategoryId
    if (type === 'person') {
        categoryId = 'person_properties'
    } else if (type === 'session') {
        categoryId = 'session_properties'
    } else if (type === 'cohort') {
        const label = key === 'all' ? 'All users' : (cohortName(Number(key)) ?? `Cohort ${key}`)
        return { categoryId: 'cohorts', key: String(key), label }
    } else if (type === 'group' && typeof groupTypeIndex === 'number') {
        categoryId = groupPropertiesCategoryId(groupTypeIndex)
    } else if (!type || type === 'event') {
        categoryId = String(key).startsWith('$feature/') ? 'feature_flags' : 'event_properties'
    } else {
        // A type the bar cannot pick, such as HogQL. Show the raw key so the chip still names it.
        return { categoryId: 'event_properties', key: String(key), label: String(key) }
    }
    return { categoryId, key: String(key), label: fieldLabelForKey(categoryId, String(key)) }
}
