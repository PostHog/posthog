import { CustomBotDefinition, CustomBotMatcher } from '~/queries/schema/schema-general'

export const CUSTOM_BOT_CATEGORY = 'custom'
export const MAX_CUSTOM_BOT_DEFINITIONS = 50
export const MAX_PATTERN_LENGTH = 200
export const MAX_NAME_LENGTH = 100

// Mirrors TRAFFIC_TYPE_BY_CATEGORY in
// products/web_analytics/backend/hogql_queries/custom_bot_definitions.py
export const CUSTOM_BOT_CATEGORY_OPTIONS: { value: string; label: string }[] = [
    { value: CUSTOM_BOT_CATEGORY, label: 'Custom' },
    { value: 'ai_crawler', label: 'AI crawler' },
    { value: 'ai_search', label: 'AI search' },
    { value: 'ai_assistant', label: 'AI assistant' },
    { value: 'search_crawler', label: 'Search crawler' },
    { value: 'seo_crawler', label: 'SEO crawler' },
    { value: 'social_crawler', label: 'Social crawler' },
    { value: 'monitoring', label: 'Monitoring' },
    { value: 'http_client', label: 'HTTP client' },
    { value: 'headless_browser', label: 'Headless browser' },
]

// ClickHouse matches these patterns with hyperscan, which supports less than JavaScript does.
// Mirrors _UNSUPPORTED_CONSTRUCTS in the Python module above, so a person sees the problem while
// typing instead of on save.
const UNSUPPORTED_CONSTRUCTS: { pattern: RegExp; label: string }[] = [
    { pattern: /\(\?=/, label: 'lookahead' },
    { pattern: /\(\?!/, label: 'lookahead' },
    { pattern: /\(\?<=/, label: 'lookbehind' },
    { pattern: /\(\?<!/, label: 'lookbehind' },
    { pattern: /\(\?>/, label: 'atomic group' },
    { pattern: /\(\?\(/, label: 'conditional group' },
    { pattern: /\(\?R/, label: 'recursion' },
    { pattern: /\\[1-9]/, label: 'backreference' },
    { pattern: /\\[zZGKCRX]/, label: 'unsupported escape' },
]

export function validateCustomBotDefinition(definition: CustomBotDefinition): string | null {
    if (!definition.name.trim()) {
        return 'Give this bot a name.'
    }
    if (definition.name.length > MAX_NAME_LENGTH) {
        return `Name cannot be longer than ${MAX_NAME_LENGTH} characters.`
    }
    if (!definition.pattern.trim()) {
        return 'Add a user agent to match.'
    }
    if (definition.pattern.length > MAX_PATTERN_LENGTH) {
        return `Pattern cannot be longer than ${MAX_PATTERN_LENGTH} characters.`
    }
    if (definition.matcher !== CustomBotMatcher.Regex) {
        return null
    }
    for (const { pattern, label } of UNSUPPORTED_CONSTRUCTS) {
        if (pattern.test(definition.pattern)) {
            return `This uses a ${label}, which is not supported here.`
        }
    }
    try {
        new RegExp(definition.pattern)
    } catch {
        return 'This is not a valid regular expression.'
    }
    return null
}

export function matchesUserAgent(definition: CustomBotDefinition, userAgent: string): boolean {
    if (validateCustomBotDefinition(definition)) {
        return false
    }
    if (definition.matcher === CustomBotMatcher.Regex) {
        try {
            return new RegExp(definition.pattern).test(userAgent)
        } catch {
            return false
        }
    }
    return userAgent.toLowerCase().includes(definition.pattern.trim().toLowerCase())
}

export function sanitizeCustomBotDefinitions(definitions: CustomBotDefinition[]): CustomBotDefinition[] {
    return definitions
        .filter((definition) => definition.name.trim() && definition.pattern.trim())
        .map((definition) => ({
            id: definition.id,
            name: definition.name.trim(),
            pattern: definition.pattern.trim(),
            matcher: definition.matcher,
            category: definition.category || CUSTOM_BOT_CATEGORY,
        }))
}
