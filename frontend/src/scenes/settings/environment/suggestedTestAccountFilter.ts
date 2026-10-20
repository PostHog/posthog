import { combineUrl } from 'kea-router'

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

export function suggestedTestAccountFilterOf(searchParams: Record<string, any>): AnyPropertyFilter | null {
    const raw = searchParams[SUGGESTED_FILTER_PARAM]
    if (!raw) {
        return null
    }
    try {
        const rule = typeof raw === 'string' ? JSON.parse(raw) : raw
        return rule && typeof rule.key === 'string' && typeof rule.type === 'string'
            ? (rule as AnyPropertyFilter)
            : null
    } catch {
        return null
    }
}

export function withoutSuggestedTestAccountFilter(searchParams: Record<string, any>): Record<string, any> {
    const { [SUGGESTED_FILTER_PARAM]: _, ...rest } = searchParams
    return rest
}
