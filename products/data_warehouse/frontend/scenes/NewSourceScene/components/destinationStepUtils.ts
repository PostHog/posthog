import type { ExternalDataSourceSyncSchema } from '~/types'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

export interface DestinationStepVisibility {
    flagEnabled: boolean
    isDirectQueryMode: boolean
    schemas: Pick<ExternalDataSourceSyncSchema, 'should_sync' | 'sync_type'>[]
    /** Set when a caller (e.g. signals setup) drives the wizard to a fixed table list. */
    requiredTables: unknown
}

/** Whether the wizard should ask for destinations before creating the source. */
export function shouldShowDestinationStep({
    flagEnabled,
    isDirectQueryMode,
    schemas,
    requiredTables,
}: DestinationStepVisibility): boolean {
    if (!flagEnabled || isDirectQueryMode || requiredTables) {
        return false
    }
    // CDC ticks a final batch continuously, so it has no run-scoped commit for a destination to
    // publish, and stays warehouse-only.
    return !schemas.some((schema) => schema.should_sync && schema.sync_type === 'cdc')
}

/**
 * What the step starts with selected.
 *
 * The PostHog warehouse, so a person who steps past this gets what they would have got before
 * destinations existed. An existing choice is left alone, so stepping back and forth keeps it.
 */
export function defaultDestinationIds(
    destinations: Pick<ExternalDataDestinationApi, 'id' | 'is_posthog_warehouse'>[],
    current: string[]
): string[] {
    if (current.length > 0) {
        return current
    }
    const warehouse = destinations.find((destination) => destination.is_posthog_warehouse)
    return warehouse ? [warehouse.id] : []
}

/** Adding or removing one destination from the picked set. */
export function toggleDestinationId(current: string[], destinationId: string): string[] {
    return current.includes(destinationId) ? current.filter((id) => id !== destinationId) : [...current, destinationId]
}
