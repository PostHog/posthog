import { OrganizationLinkStateEnumApi, PartnerAuthenticationEnumApi } from '~/generated/core/api.schemas'

export const AUTHENTICATION_LABELS: Record<PartnerAuthenticationEnumApi, string> = {
    none: 'Public client, PKCE only',
    client_secret_post: 'Client secret',
    private_key_jwt: 'Signs with a private key',
}

export const ORGANIZATION_LINK_LABELS: Record<OrganizationLinkStateEnumApi, string> = {
    this_organization: 'Linked to this organization with a verification token',
    other_region: 'Linked to an organization in another PostHog region',
    not_linked: 'Not linked. Publish a CIMD verification token to link it, so you can follow and answer its review.',
}
