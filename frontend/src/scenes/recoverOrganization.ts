import { ApiError } from 'lib/api-error'

import type { OrganizationType } from '~/types'

import * as organizationApi from 'products/platform_features/frontend/generated/api'

function isOrganizationActivationError(error: unknown): boolean {
    return (
        error instanceof ApiError &&
        error.status === 403 &&
        ['organization_deactivated', 'organization_pending_deletion'].includes(error.code ?? '')
    )
}

async function loadOrganizationFromListing(organizationId: string): Promise<OrganizationType | null> {
    let offset = 0
    while (true) {
        const page = await organizationApi.list({ limit: 100, offset })
        const organization = page.results.find(({ id }) => id === organizationId)
        if (organization) {
            // Detail and discovery share a serializer while the store uses mutable types.
            return organization as unknown as OrganizationType
        }
        if (!page.next || page.results.length === 0) {
            return null
        }
        offset += page.results.length
    }
}

export async function recoverOrganization(
    error: unknown,
    getCurrentOrganization: () => OrganizationType | null
): Promise<OrganizationType | null> {
    if (isOrganizationActivationError(error)) {
        const currentOrganization = getCurrentOrganization()
        return currentOrganization ? await loadOrganizationFromListing(currentOrganization.id) : null
    }
    if (error instanceof ApiError && error.status && error.status < 500) {
        return null
    }
    // Keep the previous organization on transient failures so the project switcher retains its teams.
    return getCurrentOrganization()
}
