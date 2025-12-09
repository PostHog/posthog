export interface FragileSelectorResult {
    isFragile: boolean
    reason: string | null
    fragileSelector: string | null
}

/**
 * Checks if a CSS selector is fragile (uses position-based matching like nth-child/nth-of-type)
 */
export function checkSelectorFragility(selector: string | null | undefined): FragileSelectorResult {
    if (!selector || selector.trim() === '') {
        return { isFragile: false, reason: null, fragileSelector: null }
    }

    // Check for position-based selectors (most fragile)
    const nthTypeMatch = selector.match(/:nth-of-type\((\d+)\)/)
    if (nthTypeMatch) {
        return { isFragile: true, reason: 'Uses position-based matching', fragileSelector: nthTypeMatch[0] }
    }

    const nthChildMatch = selector.match(/:nth-child\((\d+)\)/)
    if (nthChildMatch) {
        return { isFragile: true, reason: 'Uses position-based matching', fragileSelector: nthChildMatch[0] }
    }

    return { isFragile: false, reason: null, fragileSelector: null }
}

// Simple cache
const cache = new Map<string, FragileSelectorResult>()

export function checkSelectorFragilityCached(selector: string | null | undefined): FragileSelectorResult {
    const key = selector || ''
    const cached = cache.get(key)
    if (cached) {
        return cached
    }

    const result = checkSelectorFragility(selector)
    cache.set(key, result)

    if (cache.size > 100) {
        const firstKey = cache.keys().next().value
        if (firstKey !== undefined) {
            cache.delete(firstKey)
        }
    }

    return result
}
