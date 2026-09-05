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

export interface BroadSelectorResult {
    isBroad: boolean
    reason: string | null
}

/**
 * Checks if a CSS selector is broad: it matches on tag names and classes only, with no id or
 * attribute qualifier. Such a selector catches every element that shares the tag or class, so an
 * autocapture action built on it can count clicks on unrelated elements.
 */
export function checkSelectorBreadth(selector: string | null | undefined): BroadSelectorResult {
    if (!selector || selector.trim() === '') {
        return { isBroad: false, reason: null }
    }

    // Position-based selectors are reported by checkSelectorFragility instead
    if (/:nth-(child|of-type)\(/.test(selector)) {
        return { isBroad: false, reason: null }
    }

    // Only the rightmost (target) compound decides which elements the selector actually matches.
    // A qualifier on an ancestor, as in `#checkout-panel button`, narrows the scope but leaves the
    // target matching every button in that scope, so we judge breadth on the target compound alone.
    const target = targetCompound(selector)

    // An attribute selector (including data-*) is a qualifier. Its content begins with an
    // attribute name, so we require an identifier after the `[`. A Tailwind arbitrary-value
    // class such as `.max-w-[1045px]` or `.shadow-[0_4px_6px_rgba(0,0,0,0.1)]` also uses
    // brackets, but its content is a value (a digit, symbol, or function), which the action
    // selector parser treats as part of the class. Those still match by class only.
    if (/\[\s*[a-zA-Z_][\w:-]*\s*([~|^$*]?=|\])/.test(target)) {
        return { isBroad: false, reason: null }
    }

    // An id is a qualifier. Ignore any `#` inside a bracketed value (e.g. `[href="#x"]` or a
    // Tailwind color like `.text-[#fff]`) by stripping bracket groups before the check.
    if (target.replace(/\[[^\]]*\]/g, '').includes('#')) {
        return { isBroad: false, reason: null }
    }

    return { isBroad: true, reason: 'Matches by tag or class only' }
}

/**
 * Returns the rightmost compound of a selector: everything after the last top-level combinator
 * (descendant space, `>`, `+`, `~`). Combinator characters inside `[...]` or `(...)`, such as an
 * attribute value or a `:not(...)` argument, are skipped so they do not split a single compound.
 */
function targetCompound(selector: string): string {
    let depth = 0
    for (let i = selector.length - 1; i >= 0; i--) {
        const char = selector[i]
        if (char === ']' || char === ')') {
            depth++
        } else if (char === '[' || char === '(') {
            depth--
        } else if (depth === 0 && (char === ' ' || char === '>' || char === '+' || char === '~')) {
            return selector.slice(i + 1)
        }
    }
    return selector
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
