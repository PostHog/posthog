import type { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

export function failedDestinationFor(
    latestError: string | null | undefined,
    candidateIds: readonly string[],
    destinationsById: Record<string, ExternalDataDestinationApi>
): ExternalDataDestinationApi | null {
    if (!latestError) {
        return null
    }

    let match: ExternalDataDestinationApi | null = null
    for (const id of candidateIds) {
        const destination = destinationsById[id]
        if (!destination || destination.is_posthog_warehouse) {
            continue
        }
        const prefix = `${destination.name}: `
        if (
            (latestError.startsWith(prefix) || latestError.includes(`: ${prefix}`)) &&
            (!match || destination.name.length > match.name.length)
        ) {
            match = destination
        }
    }
    return match
}
