import type { ParsedRobots, RobotsParseHandler } from '@trybyte/robotstxt-parser'
import { Token, parseDictionary } from 'structured-headers'

import { parseJSON } from '~/common/utils/json-parse'
import { fetchStreamed } from '~/common/utils/request'

import { ConfigurationCacheItem, ConfigurationFile, HttpCacheMetadata, configurationCacheKey } from './crawl-history'
import { ImageFetchRequestMetrics } from './metrics'
import { canonicalizeUrl, politenessKey } from './politeness-key'
import { WebBotAuthRequestSigner } from './web-bot-auth'
import { wildcardPatternMatchesPathname } from './wildcard-pattern'

const BOT_NAME = 'PostHogImageFetcherBot'
const USER_AGENT = `${BOT_NAME}/1.0 (+https://posthog.com/docs/ai-research/image-fetcher-bot)`
const CONFIG_BODY_LIMIT = 500 * 1024
const CONFIG_REDIRECT_LIMIT = 5
const CONFIG_FRESH_MS = 24 * 60 * 60 * 1000
const CONFIG_REFRESH_MS = 23 * 60 * 60 * 1000
const CONFIG_RETRY_MS = 60 * 60 * 1000
const CONFIG_STORAGE_MS = 30 * 24 * 60 * 60 * 1000
const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308])

export type ConfigurationFetchResult =
    | { outcome: 'available'; body: string; cache: HttpCacheMetadata }
    | { outcome: 'absent' | 'refused' | 'unreachable'; cache?: HttpCacheMetadata }
    | { outcome: 'deferred'; reason: ConfigurationRequestBlockReason }

export type ConfigurationRequestBlockReason =
    | 'breaker_open'
    | 'backoff'
    | 'deadline'
    | 'origin_map_full'
    | 'registrable_domain_map_full'
    | 'connection_limit'

export type RobotsPolicyRefusalReason = 'robots_disallow' | 'content_usage' | 'content_signal'
export type OriginPolicyReason =
    | RobotsPolicyRefusalReason
    | 'robots_refused'
    | 'tdmrep_refused'
    | 'origin_map_full'
    | 'registrable_domain_map_full'
    | 'configuration_deferred'
    | 'configuration_unreachable'
export type ResponseOptOutReason = 'x_robots_tag' | 'content_usage' | 'tdm_reservation'

export interface ConfigurationRequestScheduler {
    run<T>(
        url: URL,
        deadlineMs: number,
        request: () => Promise<T>
    ): Promise<{ ran: true; value: T } | { ran: false; reason: ConfigurationRequestBlockReason }>
}

type ConfigurationHop =
    | { kind: 'redirect'; location: string; cache: HttpCacheMetadata }
    | { kind: 'done'; result: ConfigurationFetchResult }

export class HttpConfigurationFetcher {
    constructor(
        private readonly signer: WebBotAuthRequestSigner,
        private readonly scheduler: ConfigurationRequestScheduler,
        private readonly timeoutMs: number
    ) {}

    public async fetch(origin: string, file: ConfigurationFile): Promise<ConfigurationFetchResult> {
        const deadlineMs = Date.now() + this.timeoutMs
        let target = new URL(file === 'robots' ? '/robots.txt' : '/.well-known/tdmrep.json', origin)
        const registrableDomain = politenessKey(target.hostname)
        for (let redirects = 0; ; redirects++) {
            const canonical = canonicalizeUrl(target.toString())
            if (!canonical) {
                return { outcome: 'refused' }
            }
            target = new URL(canonical.fetch)
            let scheduled:
                | { ran: true; value: ConfigurationHop }
                | { ran: false; reason: ConfigurationRequestBlockReason }
            try {
                scheduled = await this.scheduler.run(target, deadlineMs, () => this.hop(target, file, deadlineMs))
            } catch {
                return { outcome: 'unreachable' }
            }
            if (!scheduled.ran) {
                return { outcome: 'deferred', reason: scheduled.reason }
            }
            const hop = scheduled.value
            if (hop.kind === 'done') {
                return hop.result
            }
            if (redirects >= CONFIG_REDIRECT_LIMIT) {
                return { outcome: 'unreachable', cache: hop.cache }
            }
            try {
                const redirectTarget = new URL(hop.location, target)
                if (politenessKey(redirectTarget.hostname) !== registrableDomain) {
                    return { outcome: 'unreachable', cache: hop.cache }
                }
                target = redirectTarget
            } catch {
                return { outcome: 'unreachable', cache: hop.cache }
            }
        }
    }

    private async hop(target: URL, file: ConfigurationFile, deadlineMs: number): Promise<ConfigurationHop> {
        const requestTimeMs = Date.now()
        const canonical = canonicalizeUrl(target.toString())
        let response: Awaited<ReturnType<typeof fetchStreamed>>
        try {
            response = await fetchStreamed(target.toString(), {
                timeoutMs: Math.max(1, deadlineMs - Date.now()),
                headers: {
                    'user-agent': USER_AGENT,
                    accept: file === 'robots' ? 'text/plain,*/*;q=0.1' : 'application/json,*/*;q=0.1',
                    'accept-encoding': 'identity',
                    ...this.signer.headersForGet(target.toString()),
                },
            })
        } catch (error) {
            if (canonical) {
                ImageFetchRequestMetrics.observeRequest('network_error', (Date.now() - requestTimeMs) / 1000)
            }
            throw error
        }
        const complete = (result: ConfigurationHop): ConfigurationHop => {
            if (canonical) {
                ImageFetchRequestMetrics.observeRequest(
                    ImageFetchRequestMetrics.outcomeForHttpStatus(response.status),
                    (Date.now() - requestTimeMs) / 1000
                )
            }
            return result
        }
        const cache = cacheMetadata(requestTimeMs, Date.now(), response.headerLines)
        if (REDIRECT_STATUSES.has(response.status)) {
            response.discard()
            const locations = headerValues(response.headerLines, 'location')
            const location = locations.length === 1 ? locations[0] : undefined
            return complete(
                location
                    ? { kind: 'redirect', location, cache }
                    : { kind: 'done', result: { outcome: 'unreachable', cache } }
            )
        }
        if (response.status === 404 || response.status === 410) {
            response.discard()
            return complete({ kind: 'done', result: { outcome: 'absent', cache } })
        }
        if (response.status === 429 || response.status >= 500) {
            response.discard()
            return complete({ kind: 'done', result: { outcome: 'unreachable', cache } })
        }
        if (response.status >= 400 && response.status < 500) {
            response.discard()
            return complete({ kind: 'done', result: { outcome: 'refused', cache } })
        }
        if (response.status !== 200) {
            response.discard()
            return complete({ kind: 'done', result: { outcome: 'unreachable', cache } })
        }
        const body = await response.read(CONFIG_BODY_LIMIT)
        if (body.overLimit && file === 'tdmrep') {
            return complete({ kind: 'done', result: { outcome: 'unreachable', cache } })
        }
        let text: string
        try {
            text = new TextDecoder('utf-8', { fatal: true }).decode(body.bytes, { stream: body.overLimit })
        } catch {
            return complete({ kind: 'done', result: { outcome: 'unreachable', cache } })
        }
        if (file === 'tdmrep' && !isValidTdmrepDocument(text)) {
            return complete({ kind: 'done', result: { outcome: 'unreachable', cache } })
        }
        return complete({ kind: 'done', result: { outcome: 'available', body: text, cache } })
    }
}

export interface OriginPolicyDecision {
    allowed: boolean
    transient: boolean
    reason?: OriginPolicyReason
    crawlDelayMs: number
    tdmrepReservation: boolean
    updates: ConfigurationCacheItem[]
}

export interface ConfigurationPolicyPass {
    check(url: string, cached: Map<string, ConfigurationCacheItem>, nowMs: number): Promise<OriginPolicyDecision>
}

interface ParsedRobotsConfiguration {
    matcher: ParsedRobots
    fields: Array<{ name: string; value: string }>
}

interface ParsedConfigurationCache {
    robots: Map<string, Promise<ParsedRobotsConfiguration>>
    tdmrep: Map<string, unknown>
}

export class ConfigurationPolicyService {
    private readonly inFlight = new Map<string, Promise<ConfigurationFetchResult>>()

    constructor(private readonly fetcher: HttpConfigurationFetcher) {}

    public createPass(): ConfigurationPolicyPass {
        const parsed: ParsedConfigurationCache = {
            robots: new Map(),
            tdmrep: new Map(),
        }
        return {
            check: (url, cached, nowMs) => this.checkWithParsedCache(url, cached, nowMs, parsed),
        }
    }

    public async check(
        url: string,
        cached: Map<string, ConfigurationCacheItem>,
        nowMs: number
    ): Promise<OriginPolicyDecision> {
        return await this.createPass().check(url, cached, nowMs)
    }

    private async checkWithParsedCache(
        url: string,
        cached: Map<string, ConfigurationCacheItem>,
        nowMs: number,
        parsed: ParsedConfigurationCache
    ): Promise<OriginPolicyDecision> {
        const origin = new URL(url).origin
        const [robots, tdmrep] = await Promise.all([
            this.load(origin, 'robots', cached.get(configurationCacheKey(origin, 'robots')), nowMs),
            this.load(origin, 'tdmrep', cached.get(configurationCacheKey(origin, 'tdmrep')), nowMs),
        ])
        const updates = [...robots.updates, ...tdmrep.updates]
        if (robots.item.status === 'refused') {
            return {
                allowed: false,
                transient: false,
                reason: 'robots_refused',
                crawlDelayMs: 1_000,
                tdmrepReservation: false,
                updates,
            }
        }
        if (tdmrep.item.status === 'refused') {
            return {
                allowed: false,
                transient: false,
                reason: 'tdmrep_refused',
                crawlDelayMs: 1_000,
                tdmrepReservation: false,
                updates,
            }
        }

        const robotsPolicy = robots.item.body
            ? evaluateRobotsPolicy(await parsedRobotsConfiguration(robots.item, parsed), url)
            : defaultRobotsPolicy()
        if (!robotsPolicy.allowed) {
            return {
                allowed: false,
                transient: false,
                reason: robotsPolicy.reason,
                crawlDelayMs: robotsPolicy.crawlDelayMs,
                tdmrepReservation: false,
                updates,
            }
        }
        const tdmrepReservation = Boolean(
            tdmrep.item.body && tdmrepRefuses(parsedTdmrepDocument(tdmrep.item, parsed), new URL(url))
        )
        const deferredReason = requestControlDeferralReason(robots.deferredReason, tdmrep.deferredReason)
        if (deferredReason) {
            return {
                allowed: false,
                transient: true,
                reason: deferredReason,
                crawlDelayMs: 1_000,
                tdmrepReservation: false,
                updates,
            }
        }
        if (robots.item.status === 'unreachable' || tdmrep.item.status === 'unreachable') {
            return {
                allowed: false,
                transient: true,
                reason: 'configuration_unreachable',
                crawlDelayMs: 1_000,
                tdmrepReservation: false,
                updates,
            }
        }
        return {
            allowed: true,
            transient: false,
            crawlDelayMs: robotsPolicy.crawlDelayMs,
            tdmrepReservation,
            updates,
        }
    }

    private async load(
        origin: string,
        file: ConfigurationFile,
        previous: ConfigurationCacheItem | undefined,
        nowMs: number
    ): Promise<{
        item: ConfigurationCacheItem
        updates: ConfigurationCacheItem[]
        deferredReason?: ConfigurationRequestBlockReason
    }> {
        if (previous && previous.storageExpiresAtMs <= nowMs) {
            previous = undefined
        }
        if (previous && previous.refreshAtMs > nowMs) {
            return { item: previous, updates: [] }
        }
        if (previous?.status === 'unreachable' && previous.retryAtMs > nowMs) {
            return { item: previous, updates: [] }
        }
        const key = configurationCacheKey(origin, file)
        let request = this.inFlight.get(key)
        if (!request) {
            request = this.fetcher.fetch(origin, file).finally(() => this.inFlight.delete(key))
            this.inFlight.set(key, request)
        }
        const fetched = await request
        if (fetched.outcome === 'deferred') {
            return {
                item: previous ?? unreachableItem(origin, file, nowMs),
                updates: [],
                deferredReason: fetched.reason,
            }
        }
        if (fetched.outcome === 'unreachable' && previous && previous.status !== 'unreachable') {
            const retained = {
                ...previous,
                refreshAtMs: nowMs + CONFIG_RETRY_MS,
                retryAtMs: nowMs + CONFIG_RETRY_MS,
                storageExpiresAtMs: Math.max(previous.storageExpiresAtMs, nowMs + CONFIG_STORAGE_MS),
            }
            return { item: retained, updates: [retained] }
        }
        const explicitFreshMs = fetched.cache ? explicitFreshnessLifetimeMs(fetched.cache) : 0
        const freshForMs =
            fetched.outcome === 'unreachable' ? CONFIG_RETRY_MS : Math.max(CONFIG_FRESH_MS, explicitFreshMs)
        const item: ConfigurationCacheItem = {
            kind: file,
            key,
            origin,
            status: fetched.outcome,
            body: fetched.outcome === 'available' ? fetched.body : undefined,
            fetchedAtMs: nowMs,
            refreshAtMs: nowMs + (fetched.outcome === 'unreachable' ? CONFIG_RETRY_MS : CONFIG_REFRESH_MS),
            freshUntilMs: nowMs + freshForMs,
            retryAtMs: nowMs + (fetched.outcome === 'unreachable' ? CONFIG_RETRY_MS : 0),
            storageExpiresAtMs: nowMs + Math.max(CONFIG_STORAGE_MS, freshForMs),
        }
        return { item, updates: [item] }
    }
}

function requestControlDeferralReason(
    ...reasons: Array<ConfigurationRequestBlockReason | undefined>
):
    | Extract<OriginPolicyReason, 'origin_map_full' | 'registrable_domain_map_full' | 'configuration_deferred'>
    | undefined {
    if (reasons.includes('registrable_domain_map_full')) {
        return 'registrable_domain_map_full'
    }
    if (reasons.includes('origin_map_full')) {
        return 'origin_map_full'
    }
    return reasons.some(Boolean) ? 'configuration_deferred' : undefined
}

function unreachableItem(origin: string, file: ConfigurationFile, nowMs: number): ConfigurationCacheItem {
    return {
        kind: file,
        key: configurationCacheKey(origin, file),
        origin,
        status: 'unreachable',
        fetchedAtMs: nowMs,
        refreshAtMs: nowMs + CONFIG_RETRY_MS,
        freshUntilMs: nowMs + CONFIG_RETRY_MS,
        retryAtMs: nowMs + CONFIG_RETRY_MS,
        storageExpiresAtMs: nowMs + CONFIG_STORAGE_MS,
    }
}

interface ExtensionGroup {
    userAgents: string[]
    fields: Array<{ name: string; value: string }>
}

class ExtensionCollector implements RobotsParseHandler {
    public readonly groups: ExtensionGroup[] = []
    private current: ExtensionGroup | undefined
    private hasRules = false

    handleRobotsStart(): void {}
    handleRobotsEnd(): void {}
    reportLineMetadata(): void {}

    handleUserAgent(_lineNum: number, value: string): void {
        if (!this.current || this.hasRules) {
            this.current = { userAgents: [], fields: [] }
            this.groups.push(this.current)
            this.hasRules = false
        }
        this.current.userAgents.push(value.trim().toLowerCase())
    }

    handleAllow(): void {
        this.hasRules = true
    }

    handleDisallow(): void {
        this.hasRules = true
    }

    handleSitemap(): void {
        this.hasRules = true
    }

    handleUnknownAction(_lineNum: number, action: string, value: string): void {
        if (!this.current) {
            return
        }
        this.hasRules = true
        this.current.fields.push({ name: action.trim().toLowerCase(), value: value.trim() })
    }
}

function selectedExtensionFields(
    body: string,
    parseRobotsTxt: typeof import('@trybyte/robotstxt-parser').parseRobotsTxt
): Array<{ name: string; value: string }> {
    const collector = new ExtensionCollector()
    parseRobotsTxt(body, collector)
    const bot = BOT_NAME.toLowerCase()
    const matches = collector.groups.map((group) => ({
        group,
        specificity: Math.max(
            ...group.userAgents.map((agent) => (agent !== '*' && bot.startsWith(agent) ? agent.length : 0)),
            0
        ),
        wildcard: group.userAgents.includes('*'),
    }))
    const specificity = Math.max(...matches.map((match) => match.specificity), 0)
    const selected =
        specificity > 0
            ? matches.filter((match) => match.specificity === specificity)
            : matches.filter((match) => match.wildcard)
    return selected.flatMap((match) => match.group.fields)
}

function defaultRobotsPolicy(): { allowed: true; crawlDelayMs: number } {
    return { allowed: true, crawlDelayMs: 1_000 }
}

export async function parseRobotsPolicy(
    body: string,
    url: string
): Promise<{ allowed: boolean; crawlDelayMs: number; reason?: RobotsPolicyRefusalReason }> {
    return evaluateRobotsPolicy(await parseRobotsConfiguration(body), url)
}

async function parseRobotsConfiguration(body: string): Promise<ParsedRobotsConfiguration> {
    const robotsParser = await import('@trybyte/robotstxt-parser')
    const { ParsedRobots, parseRobotsTxt } = robotsParser
    return {
        matcher: ParsedRobots.parse(body),
        fields: selectedExtensionFields(body, parseRobotsTxt),
    }
}

function evaluateRobotsPolicy(
    parsed: ParsedRobotsConfiguration,
    url: string
): { allowed: boolean; crawlDelayMs: number; reason?: RobotsPolicyRefusalReason } {
    if (!parsed.matcher.checkUrl(BOT_NAME, url).allowed) {
        return { allowed: false, crawlDelayMs: 1_000, reason: 'robots_disallow' }
    }
    const crawlDelayMs = Math.max(
        1_000,
        ...parsed.fields
            .filter((field) => field.name === 'crawl-delay')
            .flatMap((field) => {
                const value = field.value.trim()
                if (!/^\d+(?:\.\d+)?$/.test(value)) {
                    return []
                }
                // A decimal multiplied by 1000 is not always exact. 16.1 * 1000 is 16100.000000000002. The safe-integer guard below rejects that value, but README 7.9 accepts the delay.
                const milliseconds = Math.round(Number(value) * 1000)
                return Number.isSafeInteger(milliseconds) ? [milliseconds] : []
            })
    )
    if (
        contentUsageRefuses(parsed.fields.filter((field) => field.name === 'content-usage').map((field) => field.value))
    ) {
        return { allowed: false, crawlDelayMs, reason: 'content_usage' }
    }
    if (parsed.fields.some((field) => field.name === 'content-signal' && contentSignalRefuses(field.value, url))) {
        return { allowed: false, crawlDelayMs, reason: 'content_signal' }
    }
    return { allowed: true, crawlDelayMs }
}

function parseTdmrepDocument(body: string): unknown {
    try {
        return parseJSON(body)
    } catch {
        return undefined
    }
}

function tdmrepRefuses(parsed: unknown, url: URL): boolean {
    if (!Array.isArray(parsed)) {
        return false
    }
    for (const rule of parsed) {
        if (!isObject(rule) || typeof rule.location !== 'string') {
            continue
        }
        if (wildcardPatternMatchesPathname(rule.location, url.pathname)) {
            return rule['tdm-reservation'] === 1
        }
    }
    return false
}

function isValidTdmrepDocument(body: string): boolean {
    const parsed = parseTdmrepDocument(body)
    return (
        Array.isArray(parsed) &&
        parsed.every(
            (rule) =>
                isObject(rule) &&
                typeof rule.location === 'string' &&
                (rule['tdm-reservation'] === 0 || rule['tdm-reservation'] === 1)
        )
    )
}

async function parsedRobotsConfiguration(
    item: ConfigurationCacheItem,
    parsed: ParsedConfigurationCache
): Promise<ParsedRobotsConfiguration> {
    const revision = configurationRevision(item)
    let configuration = parsed.robots.get(revision)
    if (!configuration) {
        configuration = parseRobotsConfiguration(item.body ?? '')
        parsed.robots.set(revision, configuration)
    }
    return await configuration
}

function parsedTdmrepDocument(item: ConfigurationCacheItem, parsed: ParsedConfigurationCache): unknown {
    const revision = configurationRevision(item)
    if (!parsed.tdmrep.has(revision)) {
        parsed.tdmrep.set(revision, parseTdmrepDocument(item.body ?? ''))
    }
    return parsed.tdmrep.get(revision)
}

function configurationRevision(item: ConfigurationCacheItem): string {
    return `${item.key}\0${item.fetchedAtMs}`
}

function isObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function contentUsageRefuses(values: string[]): boolean {
    if (values.length === 0) {
        return false
    }
    try {
        const trainAi = parseDictionary(values.join(', ')).get('train-ai')
        return Boolean(
            trainAi && !Array.isArray(trainAi[0]) && trainAi[0] instanceof Token && trainAi[0].toString() === 'n'
        )
    } catch {
        return false
    }
}

function contentSignalRefuses(value: string, url: string): boolean {
    const trimmed = value.trim()
    const pathEnd = trimmed.startsWith('/') ? trimmed.search(/\s/) : -1
    if (pathEnd > 0 && !wildcardPatternMatchesPathname(trimmed.slice(0, pathEnd), new URL(url).pathname)) {
        return false
    }
    const preferences = (pathEnd > 0 ? trimmed.slice(pathEnd) : trimmed)
        .split(',')
        .map((part) => part.trim().split('=', 2))
    const aiTrain = preferences.filter(([name]) => name === 'ai-train').at(-1)
    return aiTrain?.[1] === 'no'
}

export function responseOptOutReason(
    headerLines: Array<{ name: string; value: string }>,
    tdmrepReservation: boolean
): ResponseOptOutReason | undefined {
    if (headerLines.some((line) => line.name === 'x-robots-tag' && xRobotsTagRefuses(line.value))) {
        return 'x_robots_tag'
    }
    if (contentUsageRefuses(headerLines.filter((line) => line.name === 'content-usage').map((line) => line.value))) {
        return 'content_usage'
    }
    const headerReservation = tdmReservationHeader(headerLines)
    if (headerReservation ?? tdmrepReservation) {
        return 'tdm_reservation'
    }
    return undefined
}

// X-Robots-Tag directives that carry a value, from https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag. A colon inside one of these does not start a bot scope.
const VALUED_X_ROBOTS_DIRECTIVES = ['unavailable_after', 'max-snippet', 'max-image-preview', 'max-video-preview']

function xRobotsTagRefuses(value: string): boolean {
    const lower = value.toLowerCase()
    const colon = lower.indexOf(':')
    // A bot scope is one token before the first colon. A valued directive looks the same, so the lane must tell the two apart. Otherwise it reads `unavailable_after: <date>, noai` as another bot's scope and ignores an opt-out that README 2.6 requires.
    // A prefix that names no listed directive reads as a bot scope. This keeps another bot's scope intact. A new valued directive therefore needs an entry in the list above, because until then the lane skips a `noai` that follows it.
    const prefix = colon >= 0 ? lower.slice(0, colon).trim() : ''
    const scoped = colon >= 0 && !prefix.includes(',') && !VALUED_X_ROBOTS_DIRECTIVES.includes(prefix)
    if (scoped && prefix !== BOT_NAME.toLowerCase()) {
        return false
    }
    const directives = scoped ? lower.slice(colon + 1) : lower
    return directives.split(',').some((directive) => ['noai', 'noimageai'].includes(directive.trim()))
}

function tdmReservationHeader(headerLines: Array<{ name: string; value: string }>): boolean | undefined {
    const values = headerLines
        .filter((line) => line.name === 'tdm-reservation')
        .flatMap((line) => line.value.split(','))
        .map((value) => value.trim())
    if (values.includes('1')) {
        return true
    }
    if (values.includes('0')) {
        return false
    }
    return undefined
}

function headerValues(headerLines: Array<{ name: string; value: string }>, name: string): string[] {
    return headerLines.filter((line) => line.name === name).map((line) => line.value)
}

function cacheMetadata(
    requestTimeMs: number,
    responseTimeMs: number,
    headerLines: Array<{ name: string; value: string }>
): HttpCacheMetadata {
    return {
        requestTimeMs,
        responseTimeMs,
        etag: singletonHeader(headerLines, 'etag'),
        lastModified: singletonHeader(headerLines, 'last-modified'),
        date: singletonHeader(headerLines, 'date'),
        age: singletonHeader(headerLines, 'age'),
        cacheControl: combinedHeader(headerLines, 'cache-control'),
        expires: singletonHeader(headerLines, 'expires'),
    }
}

function singletonHeader(headerLines: Array<{ name: string; value: string }>, name: string): string | undefined {
    const values = headerValues(headerLines, name)
    return values.length === 1 ? values[0] : undefined
}

function combinedHeader(headerLines: Array<{ name: string; value: string }>, name: string): string | undefined {
    const values = headerValues(headerLines, name)
    return values.length > 0 ? values.join(', ') : undefined
}

export function explicitFreshnessLifetimeMs(cache: HttpCacheMetadata, nowMs = Date.now()): number {
    const directives = cacheControlDirectives(cache.cacheControl)
    if (['no-cache', 'no-store', 'private', 'must-revalidate'].some((directive) => directives.has(directive))) {
        return 0
    }
    let lifetimeMs = 0
    if (directives.has('s-maxage')) {
        lifetimeMs = singletonDeltaSeconds(directives.get('s-maxage')) * 1000
    } else if (directives.has('max-age')) {
        lifetimeMs = singletonDeltaSeconds(directives.get('max-age')) * 1000
    } else if (cache.expires) {
        const expiresMs = Date.parse(cache.expires)
        const dateMs = cache.date ? Date.parse(cache.date) : cache.responseTimeMs
        if (Number.isFinite(expiresMs) && Number.isFinite(dateMs)) {
            lifetimeMs = Math.max(0, expiresMs - dateMs)
        }
    }
    const dateMs = cache.date ? Date.parse(cache.date) : cache.responseTimeMs
    const apparentAgeMs = Number.isFinite(dateMs) ? Math.max(0, cache.responseTimeMs - dateMs) : 0
    const ageValueMs = nonNegativeInteger(cache.age) * 1000
    const correctedAgeMs = ageValueMs + Math.max(0, cache.responseTimeMs - cache.requestTimeMs)
    const currentAgeMs = Math.max(apparentAgeMs, correctedAgeMs) + Math.max(0, nowMs - cache.responseTimeMs)
    return Math.max(0, lifetimeMs - currentAgeMs)
}

function cacheControlDirectives(cacheControl: string | undefined): Map<string, Array<string | undefined>> {
    const directives = new Map<string, Array<string | undefined>>()
    for (const directive of splitCommaSeparatedValues(cacheControl ?? '')) {
        const [rawName, ...rawValueParts] = directive.trim().split('=')
        const name = rawName.toLowerCase()
        if (!name) {
            continue
        }
        const rawValue = rawValueParts.length > 0 ? rawValueParts.join('=').trim() : undefined
        const value = rawValue?.startsWith('"') && rawValue.endsWith('"') ? rawValue.slice(1, -1) : rawValue
        directives.set(name, [...(directives.get(name) ?? []), value])
    }
    return directives
}

function splitCommaSeparatedValues(value: string): string[] {
    const values: string[] = []
    let start = 0
    let quoted = false
    let escaped = false
    for (let index = 0; index < value.length; index++) {
        const character = value[index]
        if (escaped) {
            escaped = false
        } else if (character === '\\' && quoted) {
            escaped = true
        } else if (character === '"') {
            quoted = !quoted
        } else if (character === ',' && !quoted) {
            values.push(value.slice(start, index))
            start = index + 1
        }
    }
    values.push(value.slice(start))
    return values
}

function singletonDeltaSeconds(values: Array<string | undefined> | undefined): number {
    return values?.length === 1 ? nonNegativeInteger(values[0]) : 0
}

function nonNegativeInteger(value: string | undefined): number {
    if (!value || !/^\d+$/.test(value.trim())) {
        return 0
    }
    const parsed = Number(value)
    return Number.isSafeInteger(parsed) ? parsed : 0
}
