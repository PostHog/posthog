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

export const VERIFICATION_EXPLAINERS = {
    verified: "PostHog verified this application, so people who connect it don't see an unverified warning.",
    notVerified:
        "People who connect this application see a warning that PostHog hasn't verified it. Ask PostHog to verify it to remove the warning.",
    notVerifiedProvisioner:
        "People who connect this application see a warning that PostHog hasn't verified it, and the first time they log in they're asked whether to keep it connected. Ask PostHog to verify it to remove both.",
    separateFromProvisioning:
        "Verification is separate from the provisioning review. It doesn't turn provisioning on, and an approved provisioning review doesn't verify the application.",
}

export const PROVISIONING_REVIEW_EXPLAINER =
    "The provisioning review decides whether this application can create PostHog accounts and resources. It doesn't change whether the application is verified."

export const SIGNING_KEY_REQUIRED = {
    title: 'Sign requests to provision',
    description:
        'PostHog refuses provisioning requests from this application until it signs them with a private key. Set token_endpoint_auth_method to private_key_jwt and publish a jwks_uri in your metadata document, then register again.',
    docsUrl: 'https://posthog.com/docs/integrate/provisioning#turn-on-key-signing',
}
