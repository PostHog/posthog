import ipaddr from 'ipaddr.js'

import { CustomBotCondition, CustomBotField, CustomBotMatcher, CustomBotRule } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

export const CUSTOM_BOT_CATEGORY = 'custom'
export const MAX_CUSTOM_BOT_RULES = 50
export const MAX_CONDITIONS_PER_RULE = 10
// The per-list and per-rule caps multiply, so the aggregate cap is what limits a query.
export const MAX_TOTAL_CONDITIONS = 100
export const MAX_PATTERN_LENGTH = 200
export const MAX_IP_RANGES_PER_CONDITION = 500
export const MAX_TOTAL_IP_RANGES = 1000
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
        return '192.0.2.0/24\n198.51.100.10-198.51.100.40'
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

type IpAddress = ipaddr.IPv4 | ipaddr.IPv6

type IpEntry =
    | { kind: 'cidr'; address: IpAddress; prefix: number }
    | { kind: 'range'; start: IpAddress; end: IpAddress }

function parseIpAddress(text: string): IpAddress | null {
    const value = text.trim()
    if (value.includes('%')) {
        return null
    }
    if (value.includes(':')) {
        const hexValue = withHexIPv4Tail(value)
        return hexValue !== null && ipaddr.IPv6.isValid(hexValue) ? ipaddr.IPv6.parse(hexValue) : null
    }
    return ipaddr.IPv4.isValidFourPartDecimal(value) ? ipaddr.IPv4.parse(value) : null
}

function withHexIPv4Tail(value: string): string | null {
    const tailStart = value.lastIndexOf(':') + 1
    const tail = value.slice(tailStart)
    if (!tail.includes('.')) {
        return value
    }
    if (!ipaddr.IPv4.isValidFourPartDecimal(tail)) {
        return null
    }
    const [a, b, c, d] = ipaddr.IPv4.parse(tail).octets
    return `${value.slice(0, tailStart)}${((a << 8) | b).toString(16)}:${((c << 8) | d).toString(16)}`
}

function parseIpRange(entry: string): IpEntry | null {
    const [startText, endText, ...extraEnds] = entry.split('-')
    const start = parseIpAddress(startText)
    const end = parseIpAddress(endText)
    return start && end && extraEnds.length === 0 ? { kind: 'range', start, end } : null
}

function parsePrefixLength(entry: string, address: IpAddress, prefixText: string | undefined): number | null {
    if (prefixText === undefined) {
        return address instanceof ipaddr.IPv4 ? 32 : 128
    }
    if (ipaddr.isValidCIDR(entry)) {
        return ipaddr.parseCIDR(entry)[1]
    }
    if (address instanceof ipaddr.IPv4 && ipaddr.IPv4.isValidFourPartDecimal(prefixText)) {
        return ipaddr.IPv4.parse(prefixText).prefixLengthFromSubnetMask()
    }
    return null
}

function parseIpNetwork(entry: string): IpEntry | null {
    const [addressText, prefixText, ...extraPrefixes] = entry.split('/')
    const address = parseIpAddress(addressText)
    if (!address || extraPrefixes.length > 0) {
        return null
    }
    const prefix = parsePrefixLength(entry, address, prefixText)
    return prefix === null ? null : { kind: 'cidr', address, prefix }
}

function parseIpEntry(entry: string): IpEntry | null {
    return entry.includes('-') ? parseIpRange(entry) : parseIpNetwork(entry)
}

function asIPv6(address: IpAddress): ipaddr.IPv6 {
    return address instanceof ipaddr.IPv4 ? address.toIPv4MappedAddress() : address
}

function compareAddresses(left: ipaddr.IPv6, right: ipaddr.IPv6): number {
    const leftBytes = left.toByteArray()
    const rightBytes = right.toByteArray()
    const index = leftBytes.findIndex((byte, position) => byte !== rightBytes[position])
    return index === -1 ? 0 : leftBytes[index] - rightBytes[index]
}

type IpBounds = { version: string; start: bigint; end: bigint }

function addressToBigInt(address: IpAddress): bigint {
    return address.toByteArray().reduce((value, byte) => (value << 8n) | BigInt(byte), 0n)
}

function ipEntryBounds(entry: IpEntry): IpBounds {
    if (entry.kind === 'range') {
        return { version: entry.start.kind(), start: addressToBigInt(entry.start), end: addressToBigInt(entry.end) }
    }
    const hostBits = BigInt((entry.address instanceof ipaddr.IPv4 ? 32 : 128) - entry.prefix)
    const start = (addressToBigInt(entry.address) >> hostBits) << hostBits
    return { version: entry.address.kind(), start, end: start + (1n << hostBits) - 1n }
}

function mergedBounds(bounds: IpBounds[]): IpBounds[] {
    const sorted = [...bounds].sort(
        (left, right) =>
            left.version.localeCompare(right.version) ||
            (left.start < right.start ? -1 : left.start > right.start ? 1 : 0)
    )
    const merged: IpBounds[] = []
    for (const current of sorted) {
        const last = merged[merged.length - 1]
        if (last && last.version === current.version && current.start <= last.end + 1n) {
            last.end = current.end > last.end ? current.end : last.end
        } else {
            merged.push({ ...current })
        }
    }
    return merged
}

function blockCount({ start, end }: IpBounds, limit: number): number {
    let count = 0
    let current = start
    while (current <= end && count <= limit) {
        let size = current === 0n ? 1n << 128n : current & -current
        while (current + size - 1n > end) {
            size >>= 1n
        }
        current += size
        count++
    }
    return count
}

function networkBlockCount(entries: (IpEntry | null)[]): number {
    const bounds = entries.flatMap((entry) => (entry ? [ipEntryBounds(entry)] : []))
    let count = 0
    for (const merged of mergedBounds(bounds)) {
        count += blockCount(merged, MAX_IP_RANGES_PER_CONDITION - count)
        if (count > MAX_IP_RANGES_PER_CONDITION) {
            break
        }
    }
    return count
}

function ipEntryError(entry: string, parsed: IpEntry | null): string | null {
    if (!parsed) {
        return `'${entry}' is not a valid IP address or range.`
    }
    if (parsed.kind === 'range') {
        if (parsed.start.kind() !== parsed.end.kind()) {
            return `In '${entry}', both ends must be the same IP version.`
        }
        if (compareAddresses(asIPv6(parsed.start), asIPv6(parsed.end)) > 0) {
            return `In '${entry}', the start comes after the end.`
        }
    }
    return null
}

function ipEntryMatches(entry: IpEntry, address: ipaddr.IPv6): boolean {
    if (entry.kind === 'cidr') {
        const prefix = entry.address instanceof ipaddr.IPv4 ? entry.prefix + 96 : entry.prefix
        return address.match(asIPv6(entry.address), prefix)
    }
    return compareAddresses(asIPv6(entry.start), address) <= 0 && compareAddresses(address, asIPv6(entry.end)) <= 0
}

export function conditionRanges(condition: CustomBotCondition): string[] {
    return (condition.patterns ?? [])
        .flatMap((value) => value.split(','))
        .map((entry) => entry.trim().replace(/\s*-\s*/, '-'))
        .filter(Boolean)
}

type IpRangeAnalysis = { ranges: string[]; entries: (IpEntry | null)[]; error: string | null; blockCount: number }

const MAX_CACHED_IP_RANGE_ANALYSES = 256
const ipRangeAnalyses = new Map<string, IpRangeAnalysis>()

function rangeListError(ranges: string[], entries: (IpEntry | null)[]): string | null {
    for (const [index, entry] of ranges.entries()) {
        if (entry.length > MAX_PATTERN_LENGTH) {
            return `An IP range cannot be longer than ${MAX_PATTERN_LENGTH} characters.`
        }
        const error = ipEntryError(entry, entries[index])
        if (error) {
            return error
        }
    }
    return null
}

function analyzeRanges(ranges: string[]): IpRangeAnalysis {
    if (ranges.length > MAX_IP_RANGES_PER_CONDITION) {
        const error = `A condition can have at most ${MAX_IP_RANGES_PER_CONDITION} IP ranges.`
        return { ranges, entries: [], error, blockCount: 0 }
    }
    const entries = ranges.map(parseIpEntry)
    const blockCount = networkBlockCount(entries)
    const blockError =
        blockCount > MAX_IP_RANGES_PER_CONDITION
            ? `These ranges cover more than ${MAX_IP_RANGES_PER_CONDITION} network blocks. Use fewer or wider ranges.`
            : null
    return { ranges, entries, error: rangeListError(ranges, entries) ?? blockError, blockCount }
}

function ipRangeAnalysis(condition: CustomBotCondition): IpRangeAnalysis {
    const cacheKey = JSON.stringify(condition.patterns ?? [])
    const cached = ipRangeAnalyses.get(cacheKey)
    if (cached) {
        return cached
    }
    const analysis = analyzeRanges(conditionRanges(condition))
    if (ipRangeAnalyses.size >= MAX_CACHED_IP_RANGE_ANALYSES) {
        ipRangeAnalyses.delete(ipRangeAnalyses.keys().next().value as string)
    }
    ipRangeAnalyses.set(cacheKey, analysis)
    return analysis
}

function validateIpRanges(condition: CustomBotCondition): string | null {
    const analysis = ipRangeAnalysis(condition)
    if (analysis.ranges.length === 0) {
        return 'Add an IP address or range to match.'
    }
    if (condition.key !== CustomBotField.IP) {
        return 'Ranges only work with the IP address property.'
    }
    return analysis.error
}

export function withMatcher(
    condition: CustomBotCondition,
    key: CustomBotField,
    matcher: CustomBotMatcher
): CustomBotCondition {
    const { pattern, patterns, ...rest } = condition
    if (matcher === CustomBotMatcher.Cidr) {
        return { ...rest, key, matcher, patterns: patterns?.length ? patterns : [pattern ?? ''] }
    }
    return { ...rest, key, matcher, pattern: pattern ?? conditionRanges(condition)[0] ?? '' }
}

export function validateCustomBotCondition(condition: CustomBotCondition): string | null {
    if (condition.matcher === CustomBotMatcher.Cidr) {
        return validateIpRanges(condition)
    }
    const value = condition.pattern ?? ''
    if (!value.trim()) {
        return 'Add a value to match.'
    }
    if (value.length > MAX_PATTERN_LENGTH) {
        return `Pattern cannot be longer than ${MAX_PATTERN_LENGTH} characters.`
    }

    if (condition.matcher !== CustomBotMatcher.Regex) {
        return null
    }
    for (const { pattern, label } of UNSUPPORTED_CONSTRUCTS) {
        if (pattern.test(value)) {
            return `This uses a ${label}, which is not supported here.`
        }
    }
    try {
        compileCustomBotRegex(value)
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

export function validateCustomBotRuleSet(rules: CustomBotRule[]): string | null {
    const total = rules.reduce((sum, rule) => sum + rule.items.length, 0)
    if (total > MAX_TOTAL_CONDITIONS) {
        return `You can have at most ${MAX_TOTAL_CONDITIONS} conditions across all rules.`
    }
    const totalRanges = rules
        .flatMap((rule) => rule.items)
        .filter((condition) => condition.matcher === CustomBotMatcher.Cidr)
        .reduce((sum, condition) => sum + ipRangeAnalysis(condition).blockCount, 0)
    if (totalRanges > MAX_TOTAL_IP_RANGES) {
        return `You can have at most ${MAX_TOTAL_IP_RANGES} IP network blocks across all rules.`
    }
    return null
}

/** Whether a condition matches one property value, mirroring how it is compiled for the query. */
export function conditionMatchesValue(condition: CustomBotCondition, value: string): boolean {
    if (!value.trim() || validateCustomBotCondition(condition)) {
        return false
    }
    if (condition.matcher === CustomBotMatcher.Cidr) {
        const candidate = parseIpAddress(value)
        if (!candidate) {
            return false
        }
        const address = asIPv6(candidate)
        return ipRangeAnalysis(condition).entries.some((entry) => entry !== null && ipEntryMatches(entry, address))
    }
    const rawPattern = condition.pattern ?? ''
    const pattern = rawPattern.trim()
    if (condition.matcher === CustomBotMatcher.Regex) {
        try {
            return compileCustomBotRegex(rawPattern).test(value)
        } catch {
            return false
        }
    }
    if (condition.matcher === CustomBotMatcher.Exact) {
        return value === pattern
    }
    return value.toLowerCase().includes(pattern.toLowerCase())
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
    const hasValues =
        typeof condition.pattern === 'string' ||
        (condition.matcher === CustomBotMatcher.Cidr &&
            Array.isArray(condition.patterns) &&
            condition.patterns.every((entry) => typeof entry === 'string'))
    return (
        hasValues &&
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
        let id = candidate && !seenIds.has(candidate) ? candidate : fallback
        // The fallback can itself collide with an explicit id that happens to share its shape.
        let suffix = 0
        while (seenIds.has(id)) {
            id = `${fallback}-${suffix++}`
        }
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
                ...withMatcher(condition, condition.key, condition.matcher),
                id: uniqueId(condition.id, `rule-${index}-${conditionIndex}`),
            })),
        })
    })
    return rules
}

function sanitizeCondition(condition: CustomBotCondition): CustomBotCondition {
    const base = { id: condition.id, key: condition.key, matcher: condition.matcher }
    if (condition.matcher === CustomBotMatcher.Cidr) {
        return { ...base, patterns: Array.from(new Set(conditionRanges(condition))) }
    }
    return { ...base, pattern: (condition.pattern ?? '').trim() }
}

export function sanitizeCustomBotRules(rules: CustomBotRule[]): CustomBotRule[] {
    return rules
        .map((rule) => ({
            id: rule.id,
            name: rule.name.trim(),
            category: rule.category || CUSTOM_BOT_CATEGORY,
            combiner: rule.combiner,
            items: rule.items
                .map(sanitizeCondition)
                .filter((condition) => (condition.patterns ? condition.patterns.length > 0 : condition.pattern)),
        }))
        .filter((rule) => rule.name && rule.items.length > 0)
}
