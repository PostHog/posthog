import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { legacyEntityToNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { ActionsNode, EventsNode, FunnelExclusion } from '~/queries/schema/schema-general'
import { ActionFilter, FilterType } from '~/types'

/**
 * Convert the events and actions emitted by the exclusion `ActionFilter` into funnel exclusion nodes.
 * `ActionFilter` splits its rows into separate `events` and `actions` buckets, so both must be read.
 * Reading only `events` silently drops action-based exclusions. Rows are re-sorted by `order` so the
 * resulting exclusions stay aligned with their step-range controls (which index exclusions by position).
 */
export function exclusionFiltersToNodes(filters: Partial<FilterType>): FunnelExclusion[] {
    return [...(filters.events || []), ...(filters.actions || [])]
        .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
        .map((entity) => {
            const baseEntity = legacyEntityToNode(entity as ActionFilter, true, MathAvailability.None) as
                | EventsNode
                | ActionsNode
            return { ...baseEntity, funnelFromStep: entity.funnel_from_step, funnelToStep: entity.funnel_to_step }
        })
}
