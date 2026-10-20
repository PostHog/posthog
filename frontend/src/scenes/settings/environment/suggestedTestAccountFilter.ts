import { combineUrl } from 'kea-router'

import { objectsEqual } from 'lib/utils/objects'

import { PropertyFilterType, PropertyOperator } from '~/types'
import type { AnyPropertyFilter } from '~/types'

// pinned: URL search param that links into this setting, renaming breaks links from other features
const SUGGESTED_FILTER_PARAM = 'suggested_test_account_filter'

export function suggestedTestAccountFilterUrl(rule: AnyPropertyFilter): string {
    return combineUrl(
        '/settings/environment-customization',
        { [SUGGESTED_FILTER_PARAM]: JSON.stringify(rule) },
        'internal-user-filtering'
    ).url
}

// Anyone can send a link with this parameter, so only the rule shape that the data checks suggest renders.
export function suggestedTestAccountFilterOf(searchParams: Record<string, any>): AnyPropertyFilter | null {
    const raw = searchParams[SUGGESTED_FILTER_PARAM]
    if (!raw) {
        return null
    }
    try {
        const rule = typeof raw === 'string' ? JSON.parse(raw) : raw
        const valid =
            typeof rule?.key === 'string' &&
            (rule.type === PropertyFilterType.Event || rule.type === PropertyFilterType.Person) &&
            rule.operator === PropertyOperator.IsNot &&
            Array.isArray(rule.value) &&
            rule.value.length > 0 &&
            rule.value.every((value: unknown) => typeof value === 'string')
        return valid ? { key: rule.key, type: rule.type, operator: rule.operator, value: rule.value } : null
    } catch {
        return null
    }
}

export function hasTestAccountFilter(rules: readonly AnyPropertyFilter[], rule: AnyPropertyFilter): boolean {
    return rules.some((existing) => objectsEqual(existing, rule))
}

export function withoutSuggestedTestAccountFilter(searchParams: Record<string, any>): Record<string, any> {
    const { [SUGGESTED_FILTER_PARAM]: _, ...rest } = searchParams
    return rest
}
