import {
    DIRECT_REFERRER,
    type ReferrerBucketEntry,
    type ResolvedTrafficSource,
    type TrafficSourceConfidence,
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

const CONFIDENCE_BY_KIND: Record<TrafficSourceKind, TrafficSourceConfidence> = {
    utm: 'high',
    referrer: 'high',
    click_id: 'medium',
    user_agent: 'low',
    direct: 'high',
}

export const resolveTrafficSource = (properties: Record<string, unknown> | undefined): ResolvedTrafficSource => {
    const utmSource = trimmedString(properties?.$utm_source)
    if (utmSource) {
        return { source: utmSource, kind: 'utm', confidence: 'high' }
    }

    const referringDomain = trimmedString(properties?.$referring_domain)
    if (referringDomain && referringDomain !== DIRECT_REFERRER) {
        return { source: referringDomain, kind: 'referrer', confidence: 'high' }
    }

    for (const rule of CLICK_ID_RULES) {
        if (trimmedString(properties?.[rule.property])) {
            return { source: rule.source, kind: 'click_id', confidence: 'medium' }
        }
    }

    const rawUserAgent = trimmedString(properties?.$raw_user_agent)
    if (rawUserAgent) {
        for (const rule of UA_RULES) {
            if (rawUserAgent.includes(rule.pattern)) {
                return { source: rule.source, kind: 'user_agent', confidence: 'low' }
            }
        }
    }

    return { source: DIRECT_REFERRER, kind: 'direct', confidence: 'high' }
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

const stringHogQL = (expr: string): string => `trim(toString(ifNull(${expr}, '')))`

interface BranchSpec {
    predicate: string
    sourceValue: string
    kindValue: TrafficSourceKind
}

const buildBranches = (
    utmSourceExpr: string,
    referringDomainExpr: string,
    rawUserAgentExpr: string
): readonly BranchSpec[] => {
    const utm = stringHogQL(utmSourceExpr)
    const ref = stringHogQL(referringDomainExpr)
    const ua = stringHogQL(rawUserAgentExpr)

    return [
        { predicate: `${utm} != ''`, sourceValue: utm, kindValue: 'utm' },
        {
            predicate: `${ref} != '' AND ${ref} != '${DIRECT_REFERRER}'`,
            sourceValue: ref,
            kindValue: 'referrer',
        },
        ...CLICK_ID_RULES.map(
            (rule): BranchSpec => ({
                predicate: `${stringHogQL(`properties.${rule.property}`)} != ''`,
                sourceValue: `'${rule.source}'`,
                kindValue: 'click_id',
            })
        ),
        ...UA_RULES.map(
            (rule): BranchSpec => ({
                predicate: `position(${ua}, '${rule.pattern}') > 0`,
                sourceValue: `'${rule.source}'`,
                kindValue: 'user_agent',
            })
        ),
    ]
}

const renderMultiIf = (
    branches: readonly BranchSpec[],
    project: (branch: BranchSpec) => string,
    fallback: string
): string => {
    const body = branches.map((branch) => `                        ${branch.predicate}, ${project(branch)}`).join(',\n')
    return `multiIf(\n${body},\n                        ${fallback}\n                    )`
}

export const buildTrafficSourceExpressions = (
    utmSourceExpr: string,
    referringDomainExpr: string,
    rawUserAgentExpr: string
): { sourceExpr: string; kindExpr: string } => {
    const branches = buildBranches(utmSourceExpr, referringDomainExpr, rawUserAgentExpr)
    return {
        sourceExpr: renderMultiIf(branches, (branch) => branch.sourceValue, `'${DIRECT_REFERRER}'`),
        kindExpr: renderMultiIf(branches, (branch) => `'${branch.kindValue}'`, `'direct'`),
    }
}

export const resolvedTrafficSourceFromHogQL = (source: string, kind: TrafficSourceKind): ResolvedTrafficSource => ({
    source: source || DIRECT_REFERRER,
    kind,
    confidence: CONFIDENCE_BY_KIND[kind],
})
