import {
    DIRECT_REFERRER,
    type ReferrerBucketEntry,
    type ResolvedTrafficSource,
    type TrafficSourceConfidence,
    type TrafficSourceKind,
} from './LiveWebAnalyticsMetricsTypes'

const isNonEmptyString = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0

export const CLICK_ID_RULES: readonly { property: string; source: string }[] = [
    { property: 'gclid', source: 'google.com' },
    { property: 'fbclid', source: 'facebook.com' },
    { property: 'msclkid', source: 'bing.com' },
    { property: 'ttclid', source: 'tiktok.com' },
    { property: 'igshid', source: 'instagram.com' },
    { property: 'twclid', source: 'x.com' },
    { property: 'li_fat_id', source: 'linkedin.com' },
]

export const UA_RULES: readonly { pattern: string; source: string }[] = [
    { pattern: 'FBAV', source: 'facebook.com' },
    { pattern: 'FBAN', source: 'facebook.com' },
    { pattern: 'Instagram ', source: 'instagram.com' },
    { pattern: 'TikTok', source: 'tiktok.com' },
    { pattern: 'musical_ly', source: 'tiktok.com' },
    { pattern: 'BytedanceWebview', source: 'tiktok.com' },
    { pattern: 'LinkedInApp', source: 'linkedin.com' },
    { pattern: 'Pinterest/', source: 'pinterest.com' },
    { pattern: 'Snapchat', source: 'snapchat.com' },
    { pattern: 'Reddit/', source: 'reddit.com' },
]

export const CLICK_ID_PROPERTIES: readonly string[] = CLICK_ID_RULES.map((rule) => rule.property)

const confidenceForKind = (kind: TrafficSourceKind): TrafficSourceConfidence => {
    if (kind === 'user_agent') {
        return 'low'
    }
    if (kind === 'click_id') {
        return 'medium'
    }
    return 'high'
}

export const resolveTrafficSource = (properties: Record<string, unknown> | undefined): ResolvedTrafficSource => {
    const utmSource = properties?.$utm_source
    if (isNonEmptyString(utmSource)) {
        return { source: utmSource.trim(), kind: 'utm', confidence: confidenceForKind('utm') }
    }

    const referringDomain = properties?.$referring_domain
    if (isNonEmptyString(referringDomain) && referringDomain !== DIRECT_REFERRER) {
        return { source: referringDomain, kind: 'referrer', confidence: confidenceForKind('referrer') }
    }

    for (const rule of CLICK_ID_RULES) {
        if (isNonEmptyString(properties?.[rule.property])) {
            return { source: rule.source, kind: 'click_id', confidence: confidenceForKind('click_id') }
        }
    }

    const rawUserAgent = properties?.$raw_user_agent
    if (isNonEmptyString(rawUserAgent)) {
        for (const rule of UA_RULES) {
            if (rawUserAgent.includes(rule.pattern)) {
                return { source: rule.source, kind: 'user_agent', confidence: confidenceForKind('user_agent') }
            }
        }
    }

    return { source: DIRECT_REFERRER, kind: 'direct', confidence: confidenceForKind('direct') }
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
    const addViews = (domain: string, views: number): void => {
        if (views > 0) {
            collapsed.set(domain, (collapsed.get(domain) ?? 0) + views)
        }
    }

    for (const entry of source.values()) {
        if (entry.kind === 'referrer') {
            addViews(entry.source, entry.count)
        } else {
            addViews(DIRECT_REFERRER, entry.count)
        }
    }

    return collapsed
}

const isSetHogQL = (expr: string): string => `${expr} IS NOT NULL AND ${expr} != ''`

export const buildTrafficSourceHogQL = (
    utmSourceExpr: string,
    referringDomainExpr: string,
    rawUserAgentExpr: string
): string => {
    const clickIdBranches = CLICK_ID_RULES.map(
        (rule) => `                        ${isSetHogQL(`properties.${rule.property}`)}, '${rule.source}'`
    ).join(',\n')
    const uaBranches = UA_RULES.map(
        (rule) =>
            `                        ${rawUserAgentExpr} IS NOT NULL AND position(${rawUserAgentExpr}, '${rule.pattern}') > 0, '${rule.source}'`
    ).join(',\n')

    return `multiIf(
                        ${isSetHogQL(utmSourceExpr)},
                            ${utmSourceExpr},

                        ${isSetHogQL(referringDomainExpr)}
                            AND ${referringDomainExpr} != '${DIRECT_REFERRER}',
                            ${referringDomainExpr},

${clickIdBranches},

${uaBranches},

                        '${DIRECT_REFERRER}'
                    )`
}

export const buildTrafficSourceKindHogQL = (
    utmSourceExpr: string,
    referringDomainExpr: string,
    rawUserAgentExpr: string
): string => {
    const clickIdBranches = CLICK_ID_RULES.map(
        (rule) => `                        ${isSetHogQL(`properties.${rule.property}`)}, 'click_id'`
    ).join(',\n')
    const uaBranches = UA_RULES.map(
        (rule) =>
            `                        ${rawUserAgentExpr} IS NOT NULL AND position(${rawUserAgentExpr}, '${rule.pattern}') > 0, 'user_agent'`
    ).join(',\n')

    return `multiIf(
                        ${isSetHogQL(utmSourceExpr)}, 'utm',

                        ${isSetHogQL(referringDomainExpr)}
                            AND ${referringDomainExpr} != '${DIRECT_REFERRER}',
                            'referrer',

${clickIdBranches},

${uaBranches},

                        'direct'
                    )`
}

export const resolvedTrafficSourceFromHogQL = (source: string, kind: TrafficSourceKind): ResolvedTrafficSource => ({
    source: source || DIRECT_REFERRER,
    kind,
    confidence: confidenceForKind(kind),
})
