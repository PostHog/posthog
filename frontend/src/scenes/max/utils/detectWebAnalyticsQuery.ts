import { BreakdownFilter, EventsNode, GroupNode, QuerySchema, TrendsQuery } from '~/queries/schema/schema-general'
import {
    isActionsNode,
    isDataVisualizationNode,
    isEventsNode,
    isFunnelsQuery,
    isGroupNode,
    isHogQLQuery,
    isInsightVizNode,
    isLifecycleQuery,
    isPathsQuery,
    isRetentionQuery,
    isStickinessQuery,
    isTrendsQuery,
    isWebGoalsQuery,
    isWebOverviewQuery,
    isWebStatsTableQuery,
    isWebVitalsPathBreakdownQuery,
    isWebVitalsQuery,
} from '~/queries/utils'
import { AnyPropertyFilter, PropertyGroupFilter, PropertyGroupFilterValue, RetentionEntity } from '~/types'

import { ThreadMessage } from '../maxThreadLogic'
import {
    isArtifactMessage,
    isMultiVisualizationMessage,
    isVisualizationArtifactContent,
    visualizationTypeToQuery,
} from '../utils'

const SIGNAL_EVENTS: ReadonlySet<string> = new Set(['$pageview', '$pageleave', '$screen', '$web_vitals'])

const SIGNAL_PROPERTY_KEYS: ReadonlySet<string> = new Set([
    '$pathname',
    '$current_url',
    '$host',
    '$referrer',
    '$referring_domain',
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_content',
    'utm_term',
    '$geoip_country_code',
    '$geoip_country_name',
    '$geoip_city_name',
    '$geoip_subdivision_1_name',
    '$geoip_continent_code',
    '$browser',
    '$browser_version',
    '$os',
    '$os_version',
    '$device_type',
    '$screen_height',
    '$screen_width',
    '$channel_type',
    '$entry_pathname',
    '$entry_referring_domain',
    '$entry_utm_source',
    '$session_entry_url',
    '$web_vitals_LCP_value',
    '$web_vitals_FCP_value',
    '$web_vitals_CLS_value',
    '$web_vitals_INP_value',
])

const QUESTION_KEYWORDS: readonly string[] = [
    'web analytics',
    'traffic',
    'website',
    'visitors',
    'unique visitor',
    'pageview',
    'page view',
    'bounce rate',
    'session duration',
    'traffic source',
    'referrer',
    'referring domain',
    'utm',
    'marketing campaign',
    'channel',
    'web vitals',
    'core web vitals',
    'top pages',
    'landing page',
    'entry page',
    'exit page',
    'marketing analytics',
]

const MAX_DEPTH = 6

function isSignalEvent(value: string | null | undefined): boolean {
    return !!value && SIGNAL_EVENTS.has(value)
}

function isSignalPropertyKey(key: unknown): boolean {
    return typeof key === 'string' && SIGNAL_PROPERTY_KEYS.has(key)
}

function hogQLStringHasSignal(sql: string): boolean {
    for (const key of SIGNAL_PROPERTY_KEYS) {
        if (sql.includes(key)) {
            return true
        }
    }
    for (const event of SIGNAL_EVENTS) {
        if (sql.includes(event)) {
            return true
        }
    }
    return false
}

function propertyFilterHasSignal(filter: AnyPropertyFilter): boolean {
    return isSignalPropertyKey((filter as { key?: unknown }).key)
}

function propertiesHaveSignal(
    properties: AnyPropertyFilter[] | PropertyGroupFilter | PropertyGroupFilterValue | undefined | null,
    depth: number
): boolean {
    if (!properties || depth > MAX_DEPTH) {
        return false
    }
    if (Array.isArray(properties)) {
        return properties.some((filter) => propertyFilterHasSignal(filter))
    }
    const values = (properties as PropertyGroupFilter | PropertyGroupFilterValue).values
    if (!Array.isArray(values)) {
        return false
    }
    return values.some((value) => {
        if (value && typeof value === 'object' && 'values' in value && Array.isArray(value.values)) {
            return propertiesHaveSignal(value as PropertyGroupFilterValue, depth + 1)
        }
        return propertyFilterHasSignal(value as AnyPropertyFilter)
    })
}

function entityHasSignal(
    entity: EventsNode | GroupNode | { event?: string | null; name?: string },
    depth: number
): boolean {
    if (depth > MAX_DEPTH) {
        return false
    }
    if (isGroupNode(entity)) {
        return entity.nodes?.some((node) => entityHasSignal(node, depth + 1)) ?? false
    }
    if (isEventsNode(entity) && (isSignalEvent(entity.event) || isSignalEvent(entity.name))) {
        return true
    }
    if (isActionsNode(entity) && isSignalEvent(entity.name)) {
        return true
    }
    const node = entity as EventsNode
    return propertiesHaveSignal(node.properties, depth + 1) || propertiesHaveSignal(node.fixedProperties, depth + 1)
}

function seriesHasSignal(series: TrendsQuery['series'] | undefined): boolean {
    return series?.some((entity) => entityHasSignal(entity, 0)) ?? false
}

function breakdownHasSignal(breakdownFilter: BreakdownFilter | undefined): boolean {
    if (!breakdownFilter) {
        return false
    }
    const { breakdown, breakdowns } = breakdownFilter
    if (Array.isArray(breakdown)) {
        if (breakdown.some((value) => isSignalPropertyKey(value))) {
            return true
        }
    } else if (isSignalPropertyKey(breakdown)) {
        return true
    }
    return breakdowns?.some((entry) => isSignalPropertyKey(entry?.property)) ?? false
}

function retentionEntityHasSignal(entity: RetentionEntity | undefined): boolean {
    if (!entity) {
        return false
    }
    return isSignalEvent(typeof entity.id === 'string' ? entity.id : undefined) || isSignalEvent(entity.name)
}

function insightQueryHasSignal(query: QuerySchema): boolean {
    const base = query as TrendsQuery
    if (seriesHasSignal(base.series)) {
        return true
    }
    if (propertiesHaveSignal(base.properties, 0)) {
        return true
    }
    if (breakdownHasSignal(base.breakdownFilter)) {
        return true
    }
    if (isRetentionQuery(query)) {
        if (
            retentionEntityHasSignal(query.retentionFilter?.targetEntity) ||
            retentionEntityHasSignal(query.retentionFilter?.returningEntity)
        ) {
            return true
        }
    }
    if (isPathsQuery(query)) {
        const pathsFilter = query.pathsFilter
        if (pathsFilter?.includeEventTypes?.some((eventType) => eventType === '$pageview')) {
            return true
        }
        if (pathsFilter?.pathsHogQLExpression && hogQLStringHasSignal(pathsFilter.pathsHogQLExpression)) {
            return true
        }
    }
    return false
}

function queryHasSignal(query: QuerySchema): boolean {
    if (
        isWebOverviewQuery(query) ||
        isWebStatsTableQuery(query) ||
        isWebGoalsQuery(query) ||
        isWebVitalsQuery(query) ||
        isWebVitalsPathBreakdownQuery(query)
    ) {
        return true
    }
    if (isInsightVizNode(query)) {
        const source = query.source
        return !!source && queryHasSignal(source as QuerySchema)
    }
    if (isDataVisualizationNode(query)) {
        const sql = query.source?.query
        return typeof sql === 'string' && hogQLStringHasSignal(sql)
    }
    if (isHogQLQuery(query)) {
        return typeof query.query === 'string' && hogQLStringHasSignal(query.query)
    }
    if (
        isTrendsQuery(query) ||
        isFunnelsQuery(query) ||
        isRetentionQuery(query) ||
        isLifecycleQuery(query) ||
        isStickinessQuery(query) ||
        isPathsQuery(query)
    ) {
        return insightQueryHasSignal(query)
    }
    return false
}

export function isWebAnalyticsRelatedQuestion(text: string | null | undefined): boolean {
    if (!text) {
        return false
    }
    const lowered = text.toLowerCase()
    return QUESTION_KEYWORDS.some((keyword) => lowered.includes(keyword))
}

export function isWebAnalyticsRelatedQuery(query: QuerySchema | null | undefined): boolean {
    if (!query) {
        return false
    }
    try {
        return queryHasSignal(query)
    } catch {
        return false
    }
}

export function isWebAnalyticsRelatedMessage(message: ThreadMessage): boolean {
    try {
        if (isArtifactMessage(message) && isVisualizationArtifactContent(message.content)) {
            return isWebAnalyticsRelatedQuery(visualizationTypeToQuery(message.content))
        }
        if (isMultiVisualizationMessage(message)) {
            return message.visualizations.some((viz) => isWebAnalyticsRelatedQuery(visualizationTypeToQuery(viz)))
        }
        if ('answer' in message) {
            return isWebAnalyticsRelatedQuery(
                visualizationTypeToQuery(message as Parameters<typeof visualizationTypeToQuery>[0])
            )
        }
        return false
    } catch {
        return false
    }
}
