import {
    DIRECT_REFERRER,
    type ReferrerBucketEntry,
    type ResolvedTrafficSource,
    type TrafficSourceKind,
} from './LiveWebAnalyticsMetricsTypes'

const trimmedString = (value: unknown): string => (typeof value === 'string' ? value.trim() : '')

interface TrafficSourceDefinition {
    source: string
    clickId?: string
    userAgentPatterns?: readonly string[]
}

export const TRAFFIC_SOURCE_DEFINITIONS: readonly TrafficSourceDefinition[] = [
    { source: 'google.com', clickId: 'gclid' },
    { source: 'facebook.com', clickId: 'fbclid', userAgentPatterns: ['FBAV', 'FBAN'] },
    { source: 'bing.com', clickId: 'msclkid' },
    { source: 'tiktok.com', clickId: 'ttclid', userAgentPatterns: ['TikTok', 'musical_ly', 'BytedanceWebview'] },
    { source: 'instagram.com', clickId: 'igshid', userAgentPatterns: ['Instagram '] },
    { source: 'x.com', clickId: 'twclid' },
    { source: 'linkedin.com', clickId: 'li_fat_id', userAgentPatterns: ['LinkedInApp'] },
    { source: 'pinterest.com', userAgentPatterns: ['Pinterest/'] },
    { source: 'snapchat.com', userAgentPatterns: ['Snapchat'] },
    { source: 'reddit.com', userAgentPatterns: ['Reddit/'] },
]

const CLICK_ID_RULES = TRAFFIC_SOURCE_DEFINITIONS.flatMap((definition) =>
    definition.clickId ? [{ property: definition.clickId, source: definition.source }] : []
)

const UA_RULES = TRAFFIC_SOURCE_DEFINITIONS.flatMap((definition) =>
    (definition.userAgentPatterns ?? []).map((pattern) => ({ pattern, source: definition.source }))
)

export const CLICK_ID_PROPERTIES: readonly string[] = CLICK_ID_RULES.map((rule) => rule.property)

export const resolveTrafficSource = (properties: Record<string, unknown> | undefined): ResolvedTrafficSource => {
    const utmSource = trimmedString(properties?.$utm_source)
    if (utmSource) {
        return { source: utmSource, kind: 'utm' }
    }

    const referringDomain = trimmedString(properties?.$referring_domain)
    if (referringDomain && referringDomain !== DIRECT_REFERRER) {
        return { source: referringDomain, kind: 'referrer' }
    }

    for (const rule of CLICK_ID_RULES) {
        if (trimmedString(properties?.[rule.property])) {
            return { source: rule.source, kind: 'click_id' }
        }
    }

    const rawUserAgent = trimmedString(properties?.$raw_user_agent)
    if (rawUserAgent) {
        for (const rule of UA_RULES) {
            if (rawUserAgent.includes(rule.pattern)) {
                return { source: rule.source, kind: 'user_agent' }
            }
        }
    }

    return { source: DIRECT_REFERRER, kind: 'direct' }
}

export const trafficSourceKey = (source: string, kind: TrafficSourceKind): string => `${kind}:${source}`

export const addReferrerEntry = (
    map: Map<string, ReferrerBucketEntry>,
    source: ResolvedTrafficSource,
    count: number
): void => {
    if (count <= 0) {
        return
    }

    const key = trafficSourceKey(source.source, source.kind)
    const existing = map.get(key)
    map.set(key, {
        ...source,
        count: (existing?.count ?? 0) + count,
    })
}

export const subtractReferrerEntry = (
    map: Map<string, ReferrerBucketEntry>,
    source: ResolvedTrafficSource,
    count: number
): void => {
    const key = trafficSourceKey(source.source, source.kind)
    const existing = map.get(key)
    if (!existing) {
        return
    }

    const nextCount = existing.count - count
    if (nextCount <= 0) {
        map.delete(key)
        return
    }

    map.set(key, { ...existing, count: nextCount })
}

export const collapseToRawReferrerEntries = (source: Map<string, ReferrerBucketEntry>): Map<string, number> => {
    const collapsed = new Map<string, number>()
    for (const entry of source.values()) {
        if (entry.count <= 0) {
            continue
        }
        const key = entry.kind === 'referrer' ? entry.source : DIRECT_REFERRER
        collapsed.set(key, (collapsed.get(key) ?? 0) + entry.count)
    }
    return collapsed
}

const stringHogQL = (expr: string): string => `trim(toString(ifNull(${expr}, '')))`

export const buildTrafficSourceExpressions = (
    utmSourceExpr: string,
    referringDomainExpr: string,
    rawUserAgentExpr: string
): { sourceExpr: string; kindExpr: string } => {
    const utm = stringHogQL(utmSourceExpr)
    const ref = stringHogQL(referringDomainExpr)
    const ua = stringHogQL(rawUserAgentExpr)

    const branches: [predicate: string, sourceValue: string, kindValue: TrafficSourceKind][] = [
        [`${utm} != ''`, utm, 'utm'],
        [`${ref} != '' AND ${ref} != '${DIRECT_REFERRER}'`, ref, 'referrer'],
        ...CLICK_ID_RULES.map(
            (rule) =>
                [`${stringHogQL(`properties.${rule.property}`)} != ''`, `'${rule.source}'`, 'click_id'] as [
                    string,
                    string,
                    TrafficSourceKind,
                ]
        ),
        ...UA_RULES.map(
            (rule) =>
                [`position(${ua}, '${rule.pattern}') > 0`, `'${rule.source}'`, 'user_agent'] as [
                    string,
                    string,
                    TrafficSourceKind,
                ]
        ),
    ]

    const multiIf = (cases: string[], fallback: string): string => `multiIf(${cases.join(', ')}, ${fallback})`

    return {
        sourceExpr: multiIf(
            branches.map(([predicate, sourceValue]) => `${predicate}, ${sourceValue}`),
            `'${DIRECT_REFERRER}'`
        ),
        kindExpr: multiIf(
            branches.map(([predicate, , kindValue]) => `${predicate}, '${kindValue}'`),
            `'direct'`
        ),
    }
}

export const resolvedTrafficSourceFromHogQL = (source: string, kind: TrafficSourceKind): ResolvedTrafficSource => ({
    source: source || DIRECT_REFERRER,
    kind,
})
