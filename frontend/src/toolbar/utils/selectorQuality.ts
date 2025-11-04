export type SelectorQuality = 'good' | 'warning' | 'fragile'

export interface SelectorIssue {
    type: 'position' | 'depth' | 'generic' | 'complex' | 'attribute-with-numbers'
    description: string
    severity: 'warning' | 'error'
}

export interface SelectorQualityResult {
    quality: SelectorQuality
    issues: SelectorIssue[]
    recommendations: string[]
    suggestedAttribute?: string
}

/**
 * Analyzes a CSS selector and returns a quality assessment with recommendations
 * for making the selector more stable and resilient to page changes.
 */
export function analyzeSelectorQuality(selector: string | null | undefined): SelectorQualityResult {
    if (!selector || selector.trim() === '') {
        return {
            quality: 'fragile',
            issues: [
                {
                    type: 'generic',
                    description: 'No selector could be generated',
                    severity: 'error',
                },
            ],
            recommendations: ['Add a data-posthog attribute to your element for stable identification'],
        }
    }

    const issues: SelectorIssue[] = []
    const recommendations: string[] = []

    // Check if selector uses preferred attributes - these are good!
    const goodAttributePatterns = [/\[data-posthog=/, /\[id=/, /#[\w-]+(?:\s|$|>)/, /\[data-testid=/]
    if (goodAttributePatterns.some((pat) => pat.test(selector))) {
        return {
            quality: 'good',
            issues: [],
            recommendations: [],
        }
    }

    // Check for position-based selectors (most fragile)
    const nthTypeMatch = selector.match(/:nth-of-type\((\d+)\)/g)
    const nthChildMatch = selector.match(/:nth-child\((\d+)\)/g)

    if (nthTypeMatch || nthChildMatch) {
        issues.push({
            type: 'position',
            description: `Uses position-based matching (${nthTypeMatch?.[0] || nthChildMatch?.[0]})`,
            severity: 'error',
        })
        recommendations.push('Add a data-posthog attribute to your element for stable identification')
    }

    if (/:first-child|:last-child/.test(selector)) {
        issues.push({
            type: 'position',
            description: 'Uses first-child or last-child which may break if elements are added',
            severity: 'warning',
        })
    }

    // Check selector depth
    const childCombinators = (selector.match(/>/g) || []).length
    const descendantCombinators = selector.split(/\s+/).length - 1 - childCombinators
    const totalDepth = childCombinators + descendantCombinators

    if (totalDepth > 4) {
        issues.push({
            type: 'depth',
            description: `Selector is ${totalDepth} levels deep - may break with page restructuring`,
            severity: 'error',
        })
        recommendations.push('Add a unique attribute closer to the target element')
    } else if (totalDepth > 2) {
        issues.push({
            type: 'depth',
            description: `Selector is ${totalDepth} levels deep`,
            severity: 'warning',
        })
    }

    // Check for generic element selectors without unique identifiers
    if (/^(div|span|button|a|input|form|section|article)\s*[>:\s]/.test(selector)) {
        issues.push({
            type: 'generic',
            description: 'Starts with generic element selector without unique identifier',
            severity: 'warning',
        })
        recommendations.push('Add a data-posthog or unique class/id to the element')
    }

    // Check for attribute selectors with numbers (often auto-generated IDs)
    if (/\[.*=["'].*\d{4,}.*["']\]/.test(selector)) {
        issues.push({
            type: 'attribute-with-numbers',
            description: 'Uses attributes with long numbers - likely auto-generated and unstable',
            severity: 'warning',
        })
    }

    // Check for complex pseudo-selectors
    if (/:not\(|:is\(|:where\(/.test(selector)) {
        issues.push({
            type: 'complex',
            description: 'Uses complex pseudo-selectors',
            severity: 'warning',
        })
    }

    // Check for wildcard selectors
    if (selector.includes('*')) {
        issues.push({
            type: 'complex',
            description: 'Uses wildcard selector (*) - may match unintended elements',
            severity: 'warning',
        })
    }

    // Determine overall quality based on issues
    let quality: SelectorQuality = 'good'

    const hasPositionIssue = issues.some((i) => i.type === 'position' && i.severity === 'error')
    const errorIssues = issues.filter((i) => i.severity === 'error').length
    const warningIssues = issues.filter((i) => i.severity === 'warning').length

    if (hasPositionIssue || errorIssues >= 2) {
        quality = 'fragile'
    } else if (errorIssues > 0 || warningIssues >= 3) {
        quality = 'warning'
    } else if (warningIssues > 0) {
        quality = 'warning'
    }

    // Add default recommendation if none were added
    if (recommendations.length === 0 && quality !== 'good') {
        recommendations.push('Consider adding a data-posthog attribute to your element for better stability')
    }

    return {
        quality,
        issues,
        recommendations,
    }
}

/**
 * Generates a suggested data-posthog attribute value based on element properties
 */
export function generateSuggestedAttribute(element: HTMLElement): string {
    // Try to use text content
    const text = element.textContent
        ?.trim()
        .toLowerCase()
        .replace(/\s+/g, '-')
        .replace(/[^a-z0-9-]/g, '')
    if (text && text.length > 0 && text.length <= 30) {
        return text
    }

    // Try to use aria-label
    const ariaLabel = element.getAttribute('aria-label')
    if (ariaLabel) {
        return ariaLabel
            .toLowerCase()
            .replace(/\s+/g, '-')
            .replace(/[^a-z0-9-]/g, '')
            .slice(0, 30)
    }

    // Try to use name attribute
    const name = element.getAttribute('name')
    if (name) {
        return name
    }

    // Fall back to tag name with context
    const tagName = element.tagName.toLowerCase()
    const className = element.className ? Array.from(element.classList)[0] : undefined

    if (className) {
        return `${tagName}-${className}`.slice(0, 30)
    }

    return `${tagName}-element`
}

/**
 * Memoization cache for selector quality results
 */
const selectorQualityCache = new Map<string, SelectorQualityResult>()

/**
 * Cached version of analyzeSelectorQuality for performance
 */
export function analyzeSelectorQualityCached(selector: string | null | undefined): SelectorQualityResult {
    const key = selector || ''

    if (selectorQualityCache.has(key)) {
        return selectorQualityCache.get(key)!
    }

    const result = analyzeSelectorQuality(selector)
    selectorQualityCache.set(key, result)

    // Clear cache if it gets too large (keep last 100 entries)
    if (selectorQualityCache.size > 100) {
        const firstKey = selectorQualityCache.keys().next().value
        if (firstKey !== undefined) {
            selectorQualityCache.delete(firstKey)
        }
    }

    return result
}
