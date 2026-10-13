import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

/** Where a destination writes, as far as its non-secret config says. Null when there is nothing to add. */
export function destinationTarget(destination: ExternalDataDestinationApi): string | null {
    if (destination.is_posthog_warehouse) {
        return 'Managed by PostHog'
    }
    const config = (destination.config ?? {}) as Record<string, unknown>
    const parts = [config.database, config.schema, config.dataset, config.bucket].filter(
        (part): part is string => typeof part === 'string' && part.length > 0
    )
    return parts.length > 0 ? parts.join('.') : null
}
