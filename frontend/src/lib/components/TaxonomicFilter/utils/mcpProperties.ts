import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { CORE_FILTER_DEFINITIONS_BY_GROUP, POSTHOG_EVENT_PROMOTED_PROPERTIES } from '~/taxonomy/taxonomy'

/**
 * MCP analytics helpers shared by the legacy taxonomic filter (`taxonomicFilterLogic.tsx`)
 * and the rebuild (`buildTaxonomicGroups.tsx`), so the two variants can't drift.
 *
 * Events captured by the @posthog/mcp SDK carry a known `$mcp_*` property schema.
 * The `mcp_properties` group in `posthog/taxonomy/taxonomy.py` (the `$mcp_`-prefixed
 * subset of event properties) is the source of truth for that schema — this module
 * only orders and highlights it. When a picker is scoped to those events, the schema
 * is surfaced as a dedicated "MCP properties" group — the same way autocapture
 * separates its element properties.
 */

export const MCP_TOOL_CALL_EVENT = '$mcp_tool_call'

/** Canonical @posthog/mcp events are `$mcp_`-prefixed — any of them qualifies, and the
 *  group always offers the full known schema (event-specific properties' popovers say
 *  which event carries them). The frozen legacy names (`mcp_tool_call`, ...) carry an
 *  unprefixed property schema, so they deliberately don't get the dedicated group. */
export function isMCPAnalyticsEventName(eventName: string): boolean {
    // eventNames is assembled dynamically by many surfaces; unlike the `.includes()`
    // scope checks alongside this one, `.startsWith` would throw on a stray null.
    return typeof eventName === 'string' && eventName.startsWith('$mcp_')
}

export function includesMCPAnalyticsEvents(eventNames: string[]): boolean {
    return eventNames.some(isMCPAnalyticsEventName)
}

/** The properties funnels and paths between tool calls pivot on, shown first — the
 *  event's promoted properties, so picker ordering and event-inspector promotion
 *  can't drift apart. The rest of the known schema follows in taxonomy order. */
const PRIORITY_MCP_PROPERTIES: string[] = POSTHOG_EVENT_PROMOTED_PROPERTIES[MCP_TOOL_CALL_EVENT]

let mcpPropertyFilterOptions: string[] | null = null

export function getMCPPropertyFilterOptions(): string[] {
    if (!mcpPropertyFilterOptions) {
        const known = Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP[TaxonomicFilterGroupType.MCPProperties])
        const prioritized = PRIORITY_MCP_PROPERTIES.filter((key) => known.includes(key))
        mcpPropertyFilterOptions = [...prioritized, ...known.filter((key) => !PRIORITY_MCP_PROPERTIES.includes(key))]
    }
    return mcpPropertyFilterOptions
}

/** Seeded into the Suggested tab when the picker is scoped to `$mcp_tool_call`, so
 *  success/failure splits are one click away. In the legacy picker `$mcp_tool_name`
 *  also lands there via the event's `primary_property`; the rebuild doesn't seed
 *  primary properties yet (`promotedPropertiesForContextEvents` is unwired), so it
 *  shows only this list. */
export const MCP_TOOL_CALL_SUGGESTED_PROPERTIES: string[] = ['$mcp_is_error']

/** When the MCP properties group is available in a picker, the known schema is
 *  excluded from Event properties so each property lives in exactly one group —
 *  mirroring how autocapture's element properties exist only in the Elements group.
 *  `$mcp_*` keys a team ingests beyond the known schema still surface under
 *  Event properties. With `requestedGroupTypes` undefined the exclusion stays off —
 *  degrading toward duplication (benign) rather than hiding properties. */
export function getMCPExcludedEventProperties(
    eventNames: string[],
    requestedGroupTypes: TaxonomicFilterGroupType[] | undefined
): string[] {
    return includesMCPAnalyticsEvents(eventNames) &&
        requestedGroupTypes?.includes(TaxonomicFilterGroupType.MCPProperties)
        ? getMCPPropertyFilterOptions()
        : []
}
