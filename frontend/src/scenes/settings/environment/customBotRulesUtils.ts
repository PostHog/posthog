import { CustomBotCondition, CustomBotField, CustomBotMatcher, CustomBotRule } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

export const CUSTOM_BOT_CATEGORY = 'custom'
export const MAX_CUSTOM_BOT_RULES = 50
export const MAX_CONDITIONS_PER_RULE = 10
export const MAX_PATTERN_LENGTH = 200
export const MAX_NAME_LENGTH = 100

// Mirrors CUSTOM_BOT_FIELDS in
// products/web_analytics/backend/hogql_queries/custom_bot_definitions.py
export const CUSTOM_BOT_FIELD_OPTIONS: { value: CustomBotField; label: string }[] = [
    { value: CustomBotField.RawUserAgent, label: 'Raw user agent' },
    { value: CustomBotField.IP, label: 'IP address' },
    { value: CustomBotField.Lib, label: 'Library' },
    { value: CustomBotField.Host, label: 'Host' },
    { value: CustomBotField.Pathname, label: 'Path name' },
    { value: CustomBotField.CurrentURL, label: 'Current URL' },
    { value: CustomBotField.Browser, label: 'Browser' },
    { value: CustomBotField.OS, label: 'OS' },
    { value: CustomBotField.BrowserLanguage, label: 'Browser language' },
    { value: CustomBotField.ScreenWidth, label: 'Screen width' },
    { value: CustomBotField.ScreenHeight, label: 'Screen height' },
    { value: CustomBotField.CountryCode, label: 'Country code' },
    { value: CustomBotField.Referrer, label: 'Referrer' },
    { value: CustomBotField.ReferringDomain, label: 'Referring domain' },
]

const MATCHER_LABELS: Record<CustomBotMatcher, string> = {
    [CustomBotMatcher.Contains]: 'contains',
    [CustomBotMatcher.Exact]: 'equals',
    [CustomBotMatcher.Regex]: 'matches regex',
    [CustomBotMatcher.Cidr]: 'is in range',
}

// "equals" and "contains" sit next to each other in the same select but differ in case handling,
// so each says which it is.
const MATCHER_TOOLTIPS: Partial<Record<CustomBotMatcher, string>> = {
    [CustomBotMatcher.Contains]: 'Case-insensitive',
    [CustomBotMatcher.Exact]: 'Case-sensitive, matches the whole value',
}

export function matcherLabel(matcher: CustomBotMatcher): string {
    return MATCHER_LABELS[matcher]
}

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

const NUMERIC_FIELDS = [CustomBotField.ScreenWidth, CustomBotField.ScreenHeight]

export function fieldLabel(key: CustomBotField): string {
    return CUSTOM_BOT_FIELD_OPTIONS.find((option) => option.value === key)?.label ?? key
}

/** Comparing an IP to a network range is the only sensible default, and only works on an IP. */
export function matcherOptionsFor(key: CustomBotField): { value: CustomBotMatcher; label: string; tooltip?: string }[] {
    const matchers =
        key === CustomBotField.IP
            ? [CustomBotMatcher.Cidr, CustomBotMatcher.Contains, CustomBotMatcher.Exact, CustomBotMatcher.Regex]
            : [CustomBotMatcher.Contains, CustomBotMatcher.Exact, CustomBotMatcher.Regex]
    return matchers.map((matcher) => ({
        value: matcher,
        label: MATCHER_LABELS[matcher],
        tooltip: MATCHER_TOOLTIPS[matcher],
    }))
}

export function defaultMatcherFor(key: CustomBotField): CustomBotMatcher {
    if (key === CustomBotField.IP) {
        return CustomBotMatcher.Cidr
    }
    // A screen dimension is a single number, so equality is the match someone means.
    return NUMERIC_FIELDS.includes(key) ? CustomBotMatcher.Exact : CustomBotMatcher.Contains
}

export function patternPlaceholderFor(key: CustomBotField, matcher: CustomBotMatcher): string {
    if (matcher === CustomBotMatcher.Cidr) {
        return '192.0.2.0/24'
    }
    if (matcher === CustomBotMatcher.Regex) {
        return key === CustomBotField.RawUserAgent ? 'AcmeBot/[0-9]+' : '^/api/'
    }
    // The contains placeholder for an IP is a prefix, which an equality match can never satisfy.
    if (matcher === CustomBotMatcher.Exact && key === CustomBotField.IP) {
        return '192.0.2.55'
    }
    return (
        {
            [CustomBotField.RawUserAgent]: 'AcmeBot',
            [CustomBotField.IP]: '192.0.2.',
            [CustomBotField.Lib]: 'posthog-python',
            [CustomBotField.Host]: 'scraper.example.com',
            [CustomBotField.Pathname]: '/api/products',
            [CustomBotField.CurrentURL]: 'example.com/api',
            [CustomBotField.Browser]: 'Chrome',
            [CustomBotField.OS]: 'Linux',
            [CustomBotField.BrowserLanguage]: '@posix',
            [CustomBotField.ScreenWidth]: '800',
            [CustomBotField.ScreenHeight]: '600',
            [CustomBotField.CountryCode]: 'US',
            [CustomBotField.Referrer]: 'scraper.example.com',
            [CustomBotField.ReferringDomain]: 'scraper.example.com',
        }[key] ?? 'AcmeBot'
    )
}

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

// Python's re (and re2) take regex flags as a leading inline group like (?i), which JavaScript
// RegExp rejects outright. The server accepts them, and a contains rule is compiled to (?i) itself,
// so translate them to JavaScript flags before compiling. Otherwise the editor would block a valid
// case-insensitive rule such as (?i)(acme|globex)bot and the tester would report no match.
//
// Only i, m and s are recognized: they are the flags JavaScript supports, and unlike re2 the
// server's re.compile rejects (?U)/(?L), so recognizing those here would accept a rule the API then
// refuses. A rarer server-valid flag like (?x) is still refused in the editor, and a validation
// error disables Save — such a rule can only be written through the API directly. Compare
// compileForPreview in lib/components/PathCleanFilters/pathCleaningUtils.ts.
const LEADING_INLINE_FLAGS = /^\(\?([ims]+)\)/

function compileCustomBotRegex(pattern: string): RegExp {
    // Consume every leading flag group and dedupe the letters: Python accepts stacked or repeated
    // groups like (?i)(?s)x and (?ii)x, while RegExp rejects both a leftover (?s) group in the body
    // and a repeated letter in the flags argument.
    let flags = ''
    let body = pattern
    let match = body.match(LEADING_INLINE_FLAGS)
    while (match) {
        for (const flag of match[1]!) {
            if (!flags.includes(flag)) {
                flags += flag
            }
        }
        body = body.slice(match[0].length)
        match = body.match(LEADING_INLINE_FLAGS)
    }
    return new RegExp(body, flags)
}

/** An address as a number, with the width of its family. Null when it does not parse. */
function parseIp(address: string): { value: bigint; width: bigint } | null {
    if (!address.includes(':')) {
        const octets = address.split('.')
        if (octets.length !== 4) {
            return null
        }
        let value = 0n
        for (const octet of octets) {
            // No leading zeros: Python's ipaddress rejects them, so the server would 400 a rule
            // the tester had called valid.
            if (!/^(0|[1-9]\d{0,2})$/.test(octet) || Number(octet) > 255) {
                return null
            }
            value = (value << 8n) | BigInt(octet)
        }
        return { value, width: 32n }
    }

    const halves = address.split('::')
    if (halves.length > 2) {
        return null
    }
    const abbreviated = halves.length === 2
    const head = halves[0] ? halves[0].split(':') : []
    const tail = abbreviated && halves[1] ? halves[1].split(':') : []
    const missing = 8 - head.length - tail.length
    if (abbreviated ? missing < 0 : missing !== 0) {
        return null
    }
    const groups = [...head, ...Array.from({ length: abbreviated ? missing : 0 }, () => '0'), ...tail]
    let value = 0n
    for (const group of groups) {
        if (!/^[0-9a-f]{1,4}$/i.test(group)) {
            return null
        }
        value = (value << 16n) | BigInt(parseInt(group, 16))
    }
    return { value, width: 128n }
}

/** Parse "192.0.2.0/24" or a bare address. The server validates with Python's `ipaddress`, which
 * is the authority — this catches a typo while it is being typed. */
function parseCidr(pattern: string): { value: bigint; width: bigint; prefix: bigint } | null {
    const [address, prefixText, ...rest] = pattern.trim().split('/')
    if (rest.length > 0) {
        return null
    }
    const parsed = parseIp(address)
    if (!parsed) {
        return null
    }
    if (prefixText === undefined) {
        return { ...parsed, prefix: parsed.width }
    }
    if (!/^\d{1,3}$/.test(prefixText) || BigInt(prefixText) > parsed.width) {
        return null
    }
    return { ...parsed, prefix: BigInt(prefixText) }
}

export function validateCustomBotCondition(condition: CustomBotCondition): string | null {
    if (!condition.pattern.trim()) {
        return condition.matcher === CustomBotMatcher.Cidr
            ? 'Add an IP address or range to match.'
            : 'Add a value to match.'
    }
    if (condition.pattern.length > MAX_PATTERN_LENGTH) {
        return `Pattern cannot be longer than ${MAX_PATTERN_LENGTH} characters.`
    }

    if (condition.matcher === CustomBotMatcher.Cidr) {
        if (condition.key !== CustomBotField.IP) {
            return 'Ranges only work with the IP address property.'
        }
        return parseCidr(condition.pattern) ? null : 'This is not a valid IP address or range.'
    }

    if (condition.matcher !== CustomBotMatcher.Regex) {
        return null
    }
    for (const { pattern, label } of UNSUPPORTED_CONSTRUCTS) {
        if (pattern.test(condition.pattern)) {
            return `This uses a ${label}, which is not supported here.`
        }
    }
    try {
        compileCustomBotRegex(condition.pattern)
    } catch {
        return 'This is not a valid regular expression.'
    }
    return null
}

export function validateCustomBotRule(rule: CustomBotRule): string | null {
    if (!rule.name.trim()) {
        return 'Give this bot a name.'
    }
    if (rule.name.length > MAX_NAME_LENGTH) {
        return `Name cannot be longer than ${MAX_NAME_LENGTH} characters.`
    }
    if (rule.items.length === 0) {
        return 'Add at least one condition.'
    }
    // Dragging a condition into a rule can exceed the cap without ever using the add button.
    if (rule.items.length > MAX_CONDITIONS_PER_RULE) {
        return `A rule can have at most ${MAX_CONDITIONS_PER_RULE} conditions.`
    }
    for (const condition of rule.items) {
        const error = validateCustomBotCondition(condition)
        if (error) {
            return error
        }
    }
    return null
}

/** Whether a condition matches one property value, mirroring how it is compiled for the query. */
export function conditionMatchesValue(condition: CustomBotCondition, value: string): boolean {
    if (!value.trim() || validateCustomBotCondition(condition)) {
        return false
    }
    if (condition.matcher === CustomBotMatcher.Cidr) {
        const network = parseCidr(condition.pattern)
        const candidate = parseIp(value.trim())
        if (!network || !candidate || network.width !== candidate.width) {
            return false
        }
        const mask = ((1n << network.prefix) - 1n) << (network.width - network.prefix)
        return (network.value & mask) === (candidate.value & mask)
    }
    if (condition.matcher === CustomBotMatcher.Regex) {
        try {
            return compileCustomBotRegex(condition.pattern).test(value)
        } catch {
            return false
        }
    }
    if (condition.matcher === CustomBotMatcher.Exact) {
        return value === condition.pattern.trim()
    }
    return value.toLowerCase().includes(condition.pattern.trim().toLowerCase())
}

/** Whether a rule matches the test values, one value per property, combined the way the query is. */
export function ruleMatchesValues(rule: CustomBotRule, values: Partial<Record<CustomBotField, string>>): boolean {
    if (validateCustomBotRule(rule)) {
        return false
    }
    const matches = rule.items.map((condition) => conditionMatchesValue(condition, values[condition.key] ?? ''))
    return rule.combiner === FilterLogicalOperator.Or ? matches.some(Boolean) : matches.every(Boolean)
}

function isCondition(value: unknown): value is CustomBotCondition {
    if (!value || typeof value !== 'object') {
        return false
    }
    const condition = value as CustomBotCondition
    // Enum membership matters: an unknown matcher would read as valid in the editor and then 400
    // on save against the server's strict parsing.
    return (
        typeof condition.pattern === 'string' &&
        CUSTOM_BOT_FIELD_OPTIONS.some((option) => option.value === condition.key) &&
        Object.values(CustomBotMatcher).includes(condition.matcher)
    )
}

/** Read stored rules, dropping entries that do not parse — including any saved by a
pre-combiner release. One bad entry must not take down the one surface that could fix it; the
caller compares lengths against the raw list to tell the user a save removes dropped entries.

Minted ids must be deterministic (index-based, not random): the saved-rules comparison runs per
render, and a random id would read as an endless unsaved change. */
export function parseCustomBotRules(raw: unknown): CustomBotRule[] {
    if (!Array.isArray(raw)) {
        return []
    }
    const rules: CustomBotRule[] = []
    // A shared or missing id collapses entries in the id-keyed drag-and-drop context.
    const seenIds = new Set<string>()
    const uniqueId = (candidate: string, fallback: string): string => {
        const id = candidate && !seenIds.has(candidate) ? candidate : fallback
        seenIds.add(id)
        return id
    }
    raw.forEach((entry, index) => {
        if (!entry || typeof entry !== 'object') {
            return
        }
        const current = entry as CustomBotRule
        if (!Array.isArray(current.items) || typeof current.name !== 'string' || !current.items.every(isCondition)) {
            return
        }
        rules.push({
            ...current,
            id: uniqueId(current.id, `rule-${index}`),
            combiner: current.combiner === FilterLogicalOperator.Or ? current.combiner : FilterLogicalOperator.And,
            items: current.items.map((condition, conditionIndex) => ({
                ...condition,
                id: uniqueId(condition.id, `rule-${index}-${conditionIndex}`),
            })),
        })
    })
    return rules
}

export function sanitizeCustomBotRules(rules: CustomBotRule[]): CustomBotRule[] {
    return rules
        .map((rule) => ({
            id: rule.id,
            name: rule.name.trim(),
            category: rule.category || CUSTOM_BOT_CATEGORY,
            combiner: rule.combiner,
            items: rule.items
                .filter((condition) => condition.pattern.trim())
                .map((condition) => ({
                    id: condition.id,
                    key: condition.key,
                    matcher: condition.matcher,
                    pattern: condition.pattern.trim(),
                })),
        }))
        .filter((rule) => rule.name && rule.items.length > 0)
}
