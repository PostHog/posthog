import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'

/**
 * MCP analytics helpers shared by the legacy taxonomic filter (`taxonomicFilterLogic.tsx`)
 * and the rebuild (`buildTaxonomicGroups.tsx`), so the two variants can't drift.
 *
 * Events captured by the @posthog/mcp SDK carry a known `$mcp_*` property schema
 * (see `mcp_properties` in `posthog/taxonomy/taxonomy.py`). When a picker is scoped
 * to those events, the schema is surfaced as a dedicated "MCP properties" group —
 * the same way autocapture separates its element properties.
 */

export const MCP_TOOL_CALL_EVENT = '$mcp_tool_call'

/** Canonical @posthog/mcp events are `$mcp_`-prefixed. The frozen legacy names
 *  (`mcp_tool_call`, ...) carry an unprefixed property schema, so they deliberately
 *  don't get the dedicated MCP properties group. */
export function isMCPAnalyticsEventName(eventName: string): boolean {
    return eventName.startsWith('$mcp_')
}

export function includesMCPAnalyticsEvents(eventNames: string[]): boolean {
    return eventNames.some(isMCPAnalyticsEventName)
}

/** The properties funnels and paths between tool calls pivot on, shown first.
 *  The rest of the known schema follows in taxonomy (alphabetical) order. */
const PRIORITY_MCP_PROPERTIES: string[] = [
    '$mcp_tool_name',
    '$mcp_tool_category',
    '$mcp_is_error',
    '$mcp_error_type',
    '$mcp_duration_ms',
    '$mcp_client_name',
    '$mcp_intent',
]

export function getMCPPropertyFilterOptions(): string[] {
    const known = Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP[TaxonomicFilterGroupType.MCPProperties])
    const prioritized = PRIORITY_MCP_PROPERTIES.filter((key) => known.includes(key))
    return [...prioritized, ...known.filter((key) => !PRIORITY_MCP_PROPERTIES.includes(key))]
}

/** Seeded into the Suggested tab when the picker is scoped to `$mcp_tool_call`,
 *  so success/failure splits are one click away. `$mcp_tool_name` already lands
 *  there via the event's `primary_property`, so it isn't repeated here. */
export const MCP_TOOL_CALL_SUGGESTED_PROPERTIES: string[] = ['$mcp_is_error']
