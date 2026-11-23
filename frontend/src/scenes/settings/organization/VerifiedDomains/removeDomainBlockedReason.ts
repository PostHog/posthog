import { OrganizationDomainType, OrganizationType } from '~/types'

// Mirrors the guard on `OrganizationDomainViewSet.destroy`: with the restriction on, an admin
// can't remove a domain if their own email would be left outside the verified ones.
export function removeDomainBlockedReason(
    domain: OrganizationDomainType,
    currentOrganization: OrganizationType | null,
    ownVerifiedDomain: OrganizationDomainType | null | undefined
): string | undefined {
    if (!currentOrganization?.enforce_verified_domains || !domain.is_verified) {
        return undefined
    }
    return ownVerifiedDomain && ownVerifiedDomain.id !== domain.id
        ? undefined
        : 'Your own email address would no longer be allowed. Turn off the domain restriction first'
}
