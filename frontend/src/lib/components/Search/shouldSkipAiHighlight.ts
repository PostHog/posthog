import { SearchItem } from './searchLogic'

/**
 * Determines whether to skip the "Ask PostHog AI" highlight and auto-highlight
 * the first real search result instead.
 *
 * Returns `true` when the query and results indicate high confidence that the
 * user wants a specific entity (not an AI answer).
 *
 * @param query - The search query string (trimmed)
 * @param realItems - The non-AI search results
 * @returns true if the first real result should be highlighted instead of AI
 */
export function shouldSkipAiHighlight(query: string, realItems: SearchItem[]): boolean {
    const trimmedQuery = query.trim()

    // Guard: no query or single character - keep AI highlighted
    if (!trimmedQuery || trimmedQuery.length === 1) {
        return false
    }

    const queryLower = trimmedQuery.toLowerCase()
    const wordCount = trimmedQuery.split(/\s+/).length

    // Guard: explicit AI intent - keep AI highlighted
    const aiIntentPatterns = ['ai', 'max', 'posthog ai', 'ask ai', 'ask posthog']
    if (aiIntentPatterns.some((pattern) => queryLower === pattern)) {
        return false
    }

    // Anti-pattern: question word prefix - keep AI highlighted
    const questionPrefixes = [
        'how ',
        'what ',
        'why ',
        'when ',
        'where ',
        'who ',
        'which ',
        'can ',
        'could ',
        'should ',
        'would ',
        'is ',
        'are ',
        'do ',
        'does ',
        'did ',
        'will ',
        'was ',
        'were ',
        'have ',
        'has ',
        'had ',
    ]
    if (questionPrefixes.some((prefix) => queryLower.startsWith(prefix))) {
        return false
    }

    // Anti-pattern: contains question mark - keep AI highlighted
    if (trimmedQuery.includes('?')) {
        return false
    }

    // Anti-pattern: analytical language - keep AI (check before navigational prefixes to prevent false positives)
    const analyticalKeywords = [
        'compare',
        'versus',
        'vs',
        'between',
        'trend',
        'analyze',
        'tell me',
        'explain',
        'help me',
        'summarize',
        'report',
    ]
    if (analyticalKeywords.some((keyword) => queryLower.includes(keyword))) {
        return false
    }

    // Anti-pattern: long sentence (4+ words, no structural identifiers) - keep AI
    // Check this early to avoid false positives from navigational prefixes like "show me"
    if (wordCount >= 4) {
        // Exception: allow if it starts with a strong navigational prefix
        const strongNavPrefixes = ['go to ', 'open ', 'navigate ', 'goto ']
        const hasStrongNav = strongNavPrefixes.some((prefix) => queryLower.startsWith(prefix))
        if (!hasStrongNav) {
            return false
        }
    }

    // Structural: UUID pattern - skip AI (always, even without results)
    const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
    if (uuidPattern.test(trimmedQuery)) {
        return true
    }

    // Structural: email pattern - skip AI (always)
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (emailPattern.test(trimmedQuery)) {
        return true
    }

    // Structural: partial email (contains @ with at least one char after) - skip AI if results exist
    if (trimmedQuery.includes('@') && trimmedQuery.indexOf('@') < trimmedQuery.length - 1 && realItems.length > 0) {
        return true
    }

    // Structural: URL/path pattern - skip AI (always)
    const urlPathPrefixes = [
        '/insights/',
        '/dashboard/',
        '/feature_flags/',
        '/experiments/',
        '/surveys/',
        '/notebooks/',
        '/cohorts/',
        '/persons/',
        '/groups/',
        '/workflows/',
        '/data-management/',
        'http://',
        'https://',
        'app.posthog.com',
        'us.posthog.com',
        'eu.posthog.com',
    ]
    if (urlPathPrefixes.some((prefix) => trimmedQuery.startsWith(prefix) || trimmedQuery.includes(prefix))) {
        return true
    }

    // Structural: numeric ID pattern - skip AI if results exist
    const numericIdPattern = /^\d+$/
    if (numericIdPattern.test(trimmedQuery) && realItems.length > 0) {
        return true
    }

    // Structural: event name pattern (starts with $ or snake_case with dots)
    const eventNamePattern = /^\$[a-z_]+$|^[a-z_]+\.[a-z_.]+$/i
    if (eventNamePattern.test(trimmedQuery) && realItems.length > 0) {
        return true
    }

    // If no results yet, keep AI highlighted (avoid jarring highlight jump when results load)
    if (realItems.length === 0) {
        return false
    }

    // Exact match: feature flag key pattern (kebab-case or snake_case with hyphens/underscores)
    // Check this BEFORE general exact match to avoid false positives
    const flagKeyPattern = /^[a-z0-9_-]+$/i
    const hasHyphenOrUnderscore = trimmedQuery.includes('-') || trimmedQuery.includes('_')
    const looksLikeFlagKey = flagKeyPattern.test(trimmedQuery) && hasHyphenOrUnderscore

    if (looksLikeFlagKey) {
        const hasFeatureFlagMatch = realItems.some(
            (item) => item.category === 'feature_flag' && (item.displayName || item.name).toLowerCase() === queryLower
        )
        if (hasFeatureFlagMatch) {
            return true
        }
        // If it looks like a flag key but doesn't match a feature_flag, don't trigger general exact match
        // Let it fall through to other heuristics
    } else {
        // Exact match: any result's name matches exactly (case-insensitive)
        // Only applies to non-flag-like queries
        const hasExactMatch = realItems.some((item) => (item.displayName || item.name).toLowerCase() === queryLower)
        if (hasExactMatch) {
            return true
        }
    }

    // Navigational prefix: go to / open / show / navigate / new / create / settings
    const navPrefixes = ['go to ', 'open ', 'show ', 'navigate ', 'goto ', 'new ', 'create ']
    if (navPrefixes.some((prefix) => queryLower.startsWith(prefix))) {
        return true
    }
    if (queryLower.startsWith('settings') || queryLower === 'setting') {
        const hasSettingsMatch = realItems.some((item) => item.category === 'settings')
        if (hasSettingsMatch) {
            return true
        }
    }

    // Short query (1-2 words) matching app, recent, data-management, or settings
    if (wordCount <= 2) {
        const hasShortMatch = realItems.some(
            (item) =>
                item.category === 'apps' ||
                item.category === 'recents' ||
                item.category === 'data-management' ||
                item.category === 'settings'
        )
        if (hasShortMatch) {
            return true
        }
    }

    // Single result - skip AI (but only if we haven't already rejected via anti-patterns)
    if (realItems.length === 1) {
        return true
    }

    // Rank-based: first result has significantly higher rank than others
    const firstItem = realItems[0]
    if (firstItem.rank != null && firstItem.rank > 0.5) {
        const secondItem = realItems[1]
        if (!secondItem || !secondItem.rank || firstItem.rank > 2 * secondItem.rank) {
            return true
        }
    }

    // Default: keep AI highlighted
    return false
}
