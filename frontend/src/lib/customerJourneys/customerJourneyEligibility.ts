export interface CustomerJourneyEnrollment {
    region: 'US' | 'EU'
    organization_id: string
    project_id: number
    registry_version: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function getCustomerJourneyEligibility(
    enabled: unknown,
    payload: unknown,
    context: { region: unknown; organization_id: unknown; project_id: unknown }
): CustomerJourneyEnrollment | null {
    if (
        enabled !== true ||
        !isRecord(payload) ||
        payload.schema_version !== 1 ||
        typeof payload.registry_version !== 'string' ||
        payload.registry_version.trim().length === 0 ||
        !Array.isArray(payload.organizations) ||
        !payload.organizations.every(
            (entry: unknown) =>
                isRecord(entry) &&
                (entry.region === 'US' || entry.region === 'EU') &&
                typeof entry.organization_id === 'string' &&
                entry.organization_id.trim().length > 0
        ) ||
        (context.region !== 'US' && context.region !== 'EU') ||
        typeof context.organization_id !== 'string' ||
        typeof context.project_id !== 'number' ||
        !Number.isSafeInteger(context.project_id) ||
        context.project_id <= 0 ||
        !payload.organizations.some(
            (entry: Record<string, unknown>) =>
                entry.region === context.region && entry.organization_id === context.organization_id
        )
    ) {
        return null
    }
    return {
        region: context.region,
        organization_id: context.organization_id,
        project_id: context.project_id,
        registry_version: payload.registry_version,
    }
}
