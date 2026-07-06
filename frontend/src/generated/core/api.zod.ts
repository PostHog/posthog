/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - core
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Manage CIMD verification tokens for an organization.
 *
 * A partner embeds the plaintext token in their CIMD metadata document as
 * `verification_token` inside the `com.posthog` object (the legacy top-level
 * `posthog_verification_token` field still works as a fallback). When PostHog fetches
 * the metadata, matching the token links the partner app to this organization and
 * grants a higher default rate limit for account provisioning.
 *
 * The plaintext value is only available on creation; we store a hash.
 */
export const cimdVerificationTokensCreateBodyLabelMax = 40

export const CimdVerificationTokensCreateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(cimdVerificationTokensCreateBodyLabelMax),
})

export const domainsCreateBodyDomainMax = 128

export const domainsCreateBodySsoEnforcementMax = 28

export const domainsCreateBodySamlEntityIdMax = 512

export const domainsCreateBodySamlAcsUrlMax = 512

export const domainsCreateBodyIdJagIssuerUrlMax = 512

export const domainsCreateBodyIdJagJwksUrlMax = 512

export const domainsCreateBodyIdJagAllowedClientsItemMax = 256

export const DomainsCreateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsCreateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsCreateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod
        .string()
        .max(domainsCreateBodySamlEntityIdMax)
        .nullish()
        .describe('SAML IdP entity ID (issuer).'),
    saml_acs_url: zod.string().max(domainsCreateBodySamlAcsUrlMax).nullish().describe('SAML single sign-on (ACS) URL.'),
    saml_x509_cert: zod.string().nullish().describe('SAML IdP X.509 signing certificate (PEM).'),
    scim_enabled: zod.boolean().optional().describe('Whether SCIM provisioning is enabled for this domain.'),
    id_jag_issuer_url: zod
        .string()
        .max(domainsCreateBodyIdJagIssuerUrlMax)
        .nullish()
        .describe('Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG on this domain.'),
    id_jag_jwks_url: zod
        .string()
        .max(domainsCreateBodyIdJagJwksUrlMax)
        .nullish()
        .describe('Override JWKS URL. Defaults to OIDC discovery on the issuer URL.'),
    id_jag_allowed_clients: zod
        .array(zod.string().max(domainsCreateBodyIdJagAllowedClientsItemMax))
        .optional()
        .describe('Allowed ID-JAG client IDs. Empty list allows any client_id.'),
    identity_provider_config: zod
        .uuid()
        .nullish()
        .describe(
            'Linked IdP configuration (SAML\/SCIM\/XAA) that backs this domain. Must belong to the same organization.'
        ),
})

export const domainsUpdateBodyDomainMax = 128

export const domainsUpdateBodySsoEnforcementMax = 28

export const domainsUpdateBodySamlEntityIdMax = 512

export const domainsUpdateBodySamlAcsUrlMax = 512

export const domainsUpdateBodyIdJagIssuerUrlMax = 512

export const domainsUpdateBodyIdJagJwksUrlMax = 512

export const domainsUpdateBodyIdJagAllowedClientsItemMax = 256

export const DomainsUpdateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsUpdateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsUpdateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod
        .string()
        .max(domainsUpdateBodySamlEntityIdMax)
        .nullish()
        .describe('SAML IdP entity ID (issuer).'),
    saml_acs_url: zod.string().max(domainsUpdateBodySamlAcsUrlMax).nullish().describe('SAML single sign-on (ACS) URL.'),
    saml_x509_cert: zod.string().nullish().describe('SAML IdP X.509 signing certificate (PEM).'),
    scim_enabled: zod.boolean().optional().describe('Whether SCIM provisioning is enabled for this domain.'),
    id_jag_issuer_url: zod
        .string()
        .max(domainsUpdateBodyIdJagIssuerUrlMax)
        .nullish()
        .describe('Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG on this domain.'),
    id_jag_jwks_url: zod
        .string()
        .max(domainsUpdateBodyIdJagJwksUrlMax)
        .nullish()
        .describe('Override JWKS URL. Defaults to OIDC discovery on the issuer URL.'),
    id_jag_allowed_clients: zod
        .array(zod.string().max(domainsUpdateBodyIdJagAllowedClientsItemMax))
        .optional()
        .describe('Allowed ID-JAG client IDs. Empty list allows any client_id.'),
    identity_provider_config: zod
        .uuid()
        .nullish()
        .describe(
            'Linked IdP configuration (SAML\/SCIM\/XAA) that backs this domain. Must belong to the same organization.'
        ),
})

export const domainsPartialUpdateBodyDomainMax = 128

export const domainsPartialUpdateBodySsoEnforcementMax = 28

export const domainsPartialUpdateBodySamlEntityIdMax = 512

export const domainsPartialUpdateBodySamlAcsUrlMax = 512

export const domainsPartialUpdateBodyIdJagIssuerUrlMax = 512

export const domainsPartialUpdateBodyIdJagJwksUrlMax = 512

export const domainsPartialUpdateBodyIdJagAllowedClientsItemMax = 256

export const DomainsPartialUpdateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsPartialUpdateBodyDomainMax).optional(),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsPartialUpdateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod
        .string()
        .max(domainsPartialUpdateBodySamlEntityIdMax)
        .nullish()
        .describe('SAML IdP entity ID (issuer).'),
    saml_acs_url: zod
        .string()
        .max(domainsPartialUpdateBodySamlAcsUrlMax)
        .nullish()
        .describe('SAML single sign-on (ACS) URL.'),
    saml_x509_cert: zod.string().nullish().describe('SAML IdP X.509 signing certificate (PEM).'),
    scim_enabled: zod.boolean().optional().describe('Whether SCIM provisioning is enabled for this domain.'),
    id_jag_issuer_url: zod
        .string()
        .max(domainsPartialUpdateBodyIdJagIssuerUrlMax)
        .nullish()
        .describe('Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG on this domain.'),
    id_jag_jwks_url: zod
        .string()
        .max(domainsPartialUpdateBodyIdJagJwksUrlMax)
        .nullish()
        .describe('Override JWKS URL. Defaults to OIDC discovery on the issuer URL.'),
    id_jag_allowed_clients: zod
        .array(zod.string().max(domainsPartialUpdateBodyIdJagAllowedClientsItemMax))
        .optional()
        .describe('Allowed ID-JAG client IDs. Empty list allows any client_id.'),
    identity_provider_config: zod
        .uuid()
        .nullish()
        .describe(
            'Linked IdP configuration (SAML\/SCIM\/XAA) that backs this domain. Must belong to the same organization.'
        ),
})

/**
 * Regenerate SCIM bearer token.
 */
export const domainsScimTokenCreateBodyDomainMax = 128

export const domainsScimTokenCreateBodySsoEnforcementMax = 28

export const domainsScimTokenCreateBodySamlEntityIdMax = 512

export const domainsScimTokenCreateBodySamlAcsUrlMax = 512

export const domainsScimTokenCreateBodyIdJagIssuerUrlMax = 512

export const domainsScimTokenCreateBodyIdJagJwksUrlMax = 512

export const domainsScimTokenCreateBodyIdJagAllowedClientsItemMax = 256

export const DomainsScimTokenCreateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsScimTokenCreateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsScimTokenCreateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod
        .string()
        .max(domainsScimTokenCreateBodySamlEntityIdMax)
        .nullish()
        .describe('SAML IdP entity ID (issuer).'),
    saml_acs_url: zod
        .string()
        .max(domainsScimTokenCreateBodySamlAcsUrlMax)
        .nullish()
        .describe('SAML single sign-on (ACS) URL.'),
    saml_x509_cert: zod.string().nullish().describe('SAML IdP X.509 signing certificate (PEM).'),
    scim_enabled: zod.boolean().optional().describe('Whether SCIM provisioning is enabled for this domain.'),
    id_jag_issuer_url: zod
        .string()
        .max(domainsScimTokenCreateBodyIdJagIssuerUrlMax)
        .nullish()
        .describe('Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG on this domain.'),
    id_jag_jwks_url: zod
        .string()
        .max(domainsScimTokenCreateBodyIdJagJwksUrlMax)
        .nullish()
        .describe('Override JWKS URL. Defaults to OIDC discovery on the issuer URL.'),
    id_jag_allowed_clients: zod
        .array(zod.string().max(domainsScimTokenCreateBodyIdJagAllowedClientsItemMax))
        .optional()
        .describe('Allowed ID-JAG client IDs. Empty list allows any client_id.'),
    identity_provider_config: zod
        .uuid()
        .nullish()
        .describe(
            'Linked IdP configuration (SAML\/SCIM\/XAA) that backs this domain. Must belong to the same organization.'
        ),
})

export const domainsVerifyCreateBodyDomainMax = 128

export const domainsVerifyCreateBodySsoEnforcementMax = 28

export const domainsVerifyCreateBodySamlEntityIdMax = 512

export const domainsVerifyCreateBodySamlAcsUrlMax = 512

export const domainsVerifyCreateBodyIdJagIssuerUrlMax = 512

export const domainsVerifyCreateBodyIdJagJwksUrlMax = 512

export const domainsVerifyCreateBodyIdJagAllowedClientsItemMax = 256

export const DomainsVerifyCreateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsVerifyCreateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsVerifyCreateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod
        .string()
        .max(domainsVerifyCreateBodySamlEntityIdMax)
        .nullish()
        .describe('SAML IdP entity ID (issuer).'),
    saml_acs_url: zod
        .string()
        .max(domainsVerifyCreateBodySamlAcsUrlMax)
        .nullish()
        .describe('SAML single sign-on (ACS) URL.'),
    saml_x509_cert: zod.string().nullish().describe('SAML IdP X.509 signing certificate (PEM).'),
    scim_enabled: zod.boolean().optional().describe('Whether SCIM provisioning is enabled for this domain.'),
    id_jag_issuer_url: zod
        .string()
        .max(domainsVerifyCreateBodyIdJagIssuerUrlMax)
        .nullish()
        .describe('Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG on this domain.'),
    id_jag_jwks_url: zod
        .string()
        .max(domainsVerifyCreateBodyIdJagJwksUrlMax)
        .nullish()
        .describe('Override JWKS URL. Defaults to OIDC discovery on the issuer URL.'),
    id_jag_allowed_clients: zod
        .array(zod.string().max(domainsVerifyCreateBodyIdJagAllowedClientsItemMax))
        .optional()
        .describe('Allowed ID-JAG client IDs. Empty list allows any client_id.'),
    identity_provider_config: zod
        .uuid()
        .nullish()
        .describe(
            'Linked IdP configuration (SAML\/SCIM\/XAA) that backs this domain. Must belong to the same organization.'
        ),
})

export const identityProviderConfigsCreateBodyNameMax = 255

export const identityProviderConfigsCreateBodySamlEntityIdMax = 512

export const identityProviderConfigsCreateBodySamlAcsUrlMax = 512

export const identityProviderConfigsCreateBodyIdJagIssuerUrlMax = 512

export const identityProviderConfigsCreateBodyIdJagJwksUrlMax = 512

export const identityProviderConfigsCreateBodyIdJagAllowedClientsItemMax = 256

export const IdentityProviderConfigsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(identityProviderConfigsCreateBodyNameMax)
        .optional()
        .describe("Display name for this IdP configuration (e.g. 'Okta production')."),
    saml_entity_id: zod
        .string()
        .max(identityProviderConfigsCreateBodySamlEntityIdMax)
        .nullish()
        .describe('SAML IdP entity ID (issuer).'),
    saml_acs_url: zod
        .string()
        .max(identityProviderConfigsCreateBodySamlAcsUrlMax)
        .nullish()
        .describe('SAML single sign-on (ACS) URL the IdP redirects to.'),
    saml_x509_cert: zod.string().nullish().describe('SAML IdP X.509 signing certificate (PEM).'),
    scim_enabled: zod
        .boolean()
        .optional()
        .describe(
            'Whether SCIM provisioning is enabled. Setting this true generates a bearer token (returned once); setting it false clears the token.'
        ),
    id_jag_issuer_url: zod
        .string()
        .max(identityProviderConfigsCreateBodyIdJagIssuerUrlMax)
        .nullish()
        .describe('Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG.'),
    id_jag_jwks_url: zod
        .string()
        .max(identityProviderConfigsCreateBodyIdJagJwksUrlMax)
        .nullish()
        .describe('Override JWKS URL. Defaults to OIDC discovery on the issuer URL.'),
    id_jag_allowed_clients: zod
        .array(zod.string().max(identityProviderConfigsCreateBodyIdJagAllowedClientsItemMax))
        .optional()
        .describe('Allowed ID-JAG client IDs. Empty list allows any client_id.'),
})

export const identityProviderConfigsUpdateBodyNameMax = 255

export const identityProviderConfigsUpdateBodySamlEntityIdMax = 512

export const identityProviderConfigsUpdateBodySamlAcsUrlMax = 512

export const identityProviderConfigsUpdateBodyIdJagIssuerUrlMax = 512

export const identityProviderConfigsUpdateBodyIdJagJwksUrlMax = 512

export const identityProviderConfigsUpdateBodyIdJagAllowedClientsItemMax = 256

export const IdentityProviderConfigsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(identityProviderConfigsUpdateBodyNameMax)
        .optional()
        .describe("Display name for this IdP configuration (e.g. 'Okta production')."),
    saml_entity_id: zod
        .string()
        .max(identityProviderConfigsUpdateBodySamlEntityIdMax)
        .nullish()
        .describe('SAML IdP entity ID (issuer).'),
    saml_acs_url: zod
        .string()
        .max(identityProviderConfigsUpdateBodySamlAcsUrlMax)
        .nullish()
        .describe('SAML single sign-on (ACS) URL the IdP redirects to.'),
    saml_x509_cert: zod.string().nullish().describe('SAML IdP X.509 signing certificate (PEM).'),
    scim_enabled: zod
        .boolean()
        .optional()
        .describe(
            'Whether SCIM provisioning is enabled. Setting this true generates a bearer token (returned once); setting it false clears the token.'
        ),
    id_jag_issuer_url: zod
        .string()
        .max(identityProviderConfigsUpdateBodyIdJagIssuerUrlMax)
        .nullish()
        .describe('Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG.'),
    id_jag_jwks_url: zod
        .string()
        .max(identityProviderConfigsUpdateBodyIdJagJwksUrlMax)
        .nullish()
        .describe('Override JWKS URL. Defaults to OIDC discovery on the issuer URL.'),
    id_jag_allowed_clients: zod
        .array(zod.string().max(identityProviderConfigsUpdateBodyIdJagAllowedClientsItemMax))
        .optional()
        .describe('Allowed ID-JAG client IDs. Empty list allows any client_id.'),
})

export const identityProviderConfigsPartialUpdateBodyNameMax = 255

export const identityProviderConfigsPartialUpdateBodySamlEntityIdMax = 512

export const identityProviderConfigsPartialUpdateBodySamlAcsUrlMax = 512

export const identityProviderConfigsPartialUpdateBodyIdJagIssuerUrlMax = 512

export const identityProviderConfigsPartialUpdateBodyIdJagJwksUrlMax = 512

export const identityProviderConfigsPartialUpdateBodyIdJagAllowedClientsItemMax = 256

export const IdentityProviderConfigsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(identityProviderConfigsPartialUpdateBodyNameMax)
        .optional()
        .describe("Display name for this IdP configuration (e.g. 'Okta production')."),
    saml_entity_id: zod
        .string()
        .max(identityProviderConfigsPartialUpdateBodySamlEntityIdMax)
        .nullish()
        .describe('SAML IdP entity ID (issuer).'),
    saml_acs_url: zod
        .string()
        .max(identityProviderConfigsPartialUpdateBodySamlAcsUrlMax)
        .nullish()
        .describe('SAML single sign-on (ACS) URL the IdP redirects to.'),
    saml_x509_cert: zod.string().nullish().describe('SAML IdP X.509 signing certificate (PEM).'),
    scim_enabled: zod
        .boolean()
        .optional()
        .describe(
            'Whether SCIM provisioning is enabled. Setting this true generates a bearer token (returned once); setting it false clears the token.'
        ),
    id_jag_issuer_url: zod
        .string()
        .max(identityProviderConfigsPartialUpdateBodyIdJagIssuerUrlMax)
        .nullish()
        .describe('Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG.'),
    id_jag_jwks_url: zod
        .string()
        .max(identityProviderConfigsPartialUpdateBodyIdJagJwksUrlMax)
        .nullish()
        .describe('Override JWKS URL. Defaults to OIDC discovery on the issuer URL.'),
    id_jag_allowed_clients: zod
        .array(zod.string().max(identityProviderConfigsPartialUpdateBodyIdJagAllowedClientsItemMax))
        .optional()
        .describe('Allowed ID-JAG client IDs. Empty list allows any client_id.'),
})

export const invitesCreateBodyTargetEmailMax = 254

export const invitesCreateBodyFirstNameMax = 30

export const invitesCreateBodySendEmailDefault = true
export const invitesCreateBodyCombinePendingInvitesDefault = false

export const InvitesCreateBody = /* @__PURE__ */ zod.object({
    target_email: zod.email().max(invitesCreateBodyTargetEmailMax),
    first_name: zod.string().max(invitesCreateBodyFirstNameMax).optional(),
    level: zod
        .union([zod.literal(1), zod.literal(8), zod.literal(15)])
        .optional()
        .describe('\* `1` - member\n\* `8` - administrator\n\* `15` - owner'),
    message: zod.string().nullish(),
    private_project_access: zod
        .unknown()
        .optional()
        .describe('List of team IDs and corresponding access levels to private projects.'),
    send_email: zod.boolean().default(invitesCreateBodySendEmailDefault),
    combine_pending_invites: zod.boolean().default(invitesCreateBodyCombinePendingInvitesDefault),
})

export const invitesBulkCreateBodyTargetEmailMax = 254

export const invitesBulkCreateBodyFirstNameMax = 30

export const invitesBulkCreateBodySendEmailDefault = true
export const invitesBulkCreateBodyCombinePendingInvitesDefault = false

export const InvitesBulkCreateBody = /* @__PURE__ */ zod.object({
    target_email: zod.email().max(invitesBulkCreateBodyTargetEmailMax),
    first_name: zod.string().max(invitesBulkCreateBodyFirstNameMax).optional(),
    level: zod
        .union([zod.literal(1), zod.literal(8), zod.literal(15)])
        .optional()
        .describe('\* `1` - member\n\* `8` - administrator\n\* `15` - owner'),
    message: zod.string().nullish(),
    private_project_access: zod
        .unknown()
        .optional()
        .describe('List of team IDs and corresponding access levels to private projects.'),
    send_email: zod.boolean().default(invitesBulkCreateBodySendEmailDefault),
    combine_pending_invites: zod.boolean().default(invitesBulkCreateBodyCombinePendingInvitesDefault),
})

/**
 * Create an onboarding delegation invite: an admin-level invite flagged as a setup delegation.
 * Sends a single dedicated delegation email and records the inviting user as having delegated.
 */
export const invitesDelegateCreateBodyMessageMax = 1000

export const invitesDelegateCreateBodyStepAtDelegationMax = 64

export const InvitesDelegateCreateBody = /* @__PURE__ */ zod.object({
    target_email: zod
        .email()
        .describe(
            "Email of the teammate who should complete setup on the inviter's behalf. Receives a PostHog-branded delegation invite granting admin-level membership on accept."
        ),
    message: zod
        .string()
        .max(invitesDelegateCreateBodyMessageMax)
        .optional()
        .describe('Optional personal message included in the delegation email (up to 1000 characters).'),
    step_at_delegation: zod
        .string()
        .max(invitesDelegateCreateBodyStepAtDelegationMax)
        .optional()
        .describe('Onboarding step key the delegator was on when delegating, for analytics only.'),
})

/**
 * Projects for the current organization.
 */
export const organizationsProjectsCreateBodyNameMax = 200

export const organizationsProjectsCreateBodyProductDescriptionMax = 1000

export const organizationsProjectsCreateBodyAppUrlsItemMax = 200

export const organizationsProjectsCreateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsCreateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const organizationsProjectsCreateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsCreateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsCreateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsCreateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsCreateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsCreateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsCreateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsCreateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsCreateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod.array(zod.string().max(organizationsProjectsCreateBodyAppUrlsItemMax).nullable()).optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal\/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal\/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America\/Los_Angeles`).\n\n\* `Africa\/Abidjan` - Africa\/Abidjan\n\* `Africa\/Accra` - Africa\/Accra\n\* `Africa\/Addis_Ababa` - Africa\/Addis_Ababa\n\* `Africa\/Algiers` - Africa\/Algiers\n\* `Africa\/Asmara` - Africa\/Asmara\n\* `Africa\/Asmera` - Africa\/Asmera\n\* `Africa\/Bamako` - Africa\/Bamako\n\* `Africa\/Bangui` - Africa\/Bangui\n\* `Africa\/Banjul` - Africa\/Banjul\n\* `Africa\/Bissau` - Africa\/Bissau\n\* `Africa\/Blantyre` - Africa\/Blantyre\n\* `Africa\/Brazzaville` - Africa\/Brazzaville\n\* `Africa\/Bujumbura` - Africa\/Bujumbura\n\* `Africa\/Cairo` - Africa\/Cairo\n\* `Africa\/Casablanca` - Africa\/Casablanca\n\* `Africa\/Ceuta` - Africa\/Ceuta\n\* `Africa\/Conakry` - Africa\/Conakry\n\* `Africa\/Dakar` - Africa\/Dakar\n\* `Africa\/Dar_es_Salaam` - Africa\/Dar_es_Salaam\n\* `Africa\/Djibouti` - Africa\/Djibouti\n\* `Africa\/Douala` - Africa\/Douala\n\* `Africa\/El_Aaiun` - Africa\/El_Aaiun\n\* `Africa\/Freetown` - Africa\/Freetown\n\* `Africa\/Gaborone` - Africa\/Gaborone\n\* `Africa\/Harare` - Africa\/Harare\n\* `Africa\/Johannesburg` - Africa\/Johannesburg\n\* `Africa\/Juba` - Africa\/Juba\n\* `Africa\/Kampala` - Africa\/Kampala\n\* `Africa\/Khartoum` - Africa\/Khartoum\n\* `Africa\/Kigali` - Africa\/Kigali\n\* `Africa\/Kinshasa` - Africa\/Kinshasa\n\* `Africa\/Lagos` - Africa\/Lagos\n\* `Africa\/Libreville` - Africa\/Libreville\n\* `Africa\/Lome` - Africa\/Lome\n\* `Africa\/Luanda` - Africa\/Luanda\n\* `Africa\/Lubumbashi` - Africa\/Lubumbashi\n\* `Africa\/Lusaka` - Africa\/Lusaka\n\* `Africa\/Malabo` - Africa\/Malabo\n\* `Africa\/Maputo` - Africa\/Maputo\n\* `Africa\/Maseru` - Africa\/Maseru\n\* `Africa\/Mbabane` - Africa\/Mbabane\n\* `Africa\/Mogadishu` - Africa\/Mogadishu\n\* `Africa\/Monrovia` - Africa\/Monrovia\n\* `Africa\/Nairobi` - Africa\/Nairobi\n\* `Africa\/Ndjamena` - Africa\/Ndjamena\n\* `Africa\/Niamey` - Africa\/Niamey\n\* `Africa\/Nouakchott` - Africa\/Nouakchott\n\* `Africa\/Ouagadougou` - Africa\/Ouagadougou\n\* `Africa\/Porto-Novo` - Africa\/Porto-Novo\n\* `Africa\/Sao_Tome` - Africa\/Sao_Tome\n\* `Africa\/Timbuktu` - Africa\/Timbuktu\n\* `Africa\/Tripoli` - Africa\/Tripoli\n\* `Africa\/Tunis` - Africa\/Tunis\n\* `Africa\/Windhoek` - Africa\/Windhoek\n\* `America\/Adak` - America\/Adak\n\* `America\/Anchorage` - America\/Anchorage\n\* `America\/Anguilla` - America\/Anguilla\n\* `America\/Antigua` - America\/Antigua\n\* `America\/Araguaina` - America\/Araguaina\n\* `America\/Argentina\/Buenos_Aires` - America\/Argentina\/Buenos_Aires\n\* `America\/Argentina\/Catamarca` - America\/Argentina\/Catamarca\n\* `America\/Argentina\/ComodRivadavia` - America\/Argentina\/ComodRivadavia\n\* `America\/Argentina\/Cordoba` - America\/Argentina\/Cordoba\n\* `America\/Argentina\/Jujuy` - America\/Argentina\/Jujuy\n\* `America\/Argentina\/La_Rioja` - America\/Argentina\/La_Rioja\n\* `America\/Argentina\/Mendoza` - America\/Argentina\/Mendoza\n\* `America\/Argentina\/Rio_Gallegos` - America\/Argentina\/Rio_Gallegos\n\* `America\/Argentina\/Salta` - America\/Argentina\/Salta\n\* `America\/Argentina\/San_Juan` - America\/Argentina\/San_Juan\n\* `America\/Argentina\/San_Luis` - America\/Argentina\/San_Luis\n\* `America\/Argentina\/Tucuman` - America\/Argentina\/Tucuman\n\* `America\/Argentina\/Ushuaia` - America\/Argentina\/Ushuaia\n\* `America\/Aruba` - America\/Aruba\n\* `America\/Asuncion` - America\/Asuncion\n\* `America\/Atikokan` - America\/Atikokan\n\* `America\/Atka` - America\/Atka\n\* `America\/Bahia` - America\/Bahia\n\* `America\/Bahia_Banderas` - America\/Bahia_Banderas\n\* `America\/Barbados` - America\/Barbados\n\* `America\/Belem` - America\/Belem\n\* `America\/Belize` - America\/Belize\n\* `America\/Blanc-Sablon` - America\/Blanc-Sablon\n\* `America\/Boa_Vista` - America\/Boa_Vista\n\* `America\/Bogota` - America\/Bogota\n\* `America\/Boise` - America\/Boise\n\* `America\/Buenos_Aires` - America\/Buenos_Aires\n\* `America\/Cambridge_Bay` - America\/Cambridge_Bay\n\* `America\/Campo_Grande` - America\/Campo_Grande\n\* `America\/Cancun` - America\/Cancun\n\* `America\/Caracas` - America\/Caracas\n\* `America\/Catamarca` - America\/Catamarca\n\* `America\/Cayenne` - America\/Cayenne\n\* `America\/Cayman` - America\/Cayman\n\* `America\/Chicago` - America\/Chicago\n\* `America\/Chihuahua` - America\/Chihuahua\n\* `America\/Ciudad_Juarez` - America\/Ciudad_Juarez\n\* `America\/Coral_Harbour` - America\/Coral_Harbour\n\* `America\/Cordoba` - America\/Cordoba\n\* `America\/Costa_Rica` - America\/Costa_Rica\n\* `America\/Creston` - America\/Creston\n\* `America\/Cuiaba` - America\/Cuiaba\n\* `America\/Curacao` - America\/Curacao\n\* `America\/Danmarkshavn` - America\/Danmarkshavn\n\* `America\/Dawson` - America\/Dawson\n\* `America\/Dawson_Creek` - America\/Dawson_Creek\n\* `America\/Denver` - America\/Denver\n\* `America\/Detroit` - America\/Detroit\n\* `America\/Dominica` - America\/Dominica\n\* `America\/Edmonton` - America\/Edmonton\n\* `America\/Eirunepe` - America\/Eirunepe\n\* `America\/El_Salvador` - America\/El_Salvador\n\* `America\/Ensenada` - America\/Ensenada\n\* `America\/Fort_Nelson` - America\/Fort_Nelson\n\* `America\/Fort_Wayne` - America\/Fort_Wayne\n\* `America\/Fortaleza` - America\/Fortaleza\n\* `America\/Glace_Bay` - America\/Glace_Bay\n\* `America\/Godthab` - America\/Godthab\n\* `America\/Goose_Bay` - America\/Goose_Bay\n\* `America\/Grand_Turk` - America\/Grand_Turk\n\* `America\/Grenada` - America\/Grenada\n\* `America\/Guadeloupe` - America\/Guadeloupe\n\* `America\/Guatemala` - America\/Guatemala\n\* `America\/Guayaquil` - America\/Guayaquil\n\* `America\/Guyana` - America\/Guyana\n\* `America\/Halifax` - America\/Halifax\n\* `America\/Havana` - America\/Havana\n\* `America\/Hermosillo` - America\/Hermosillo\n\* `America\/Indiana\/Indianapolis` - America\/Indiana\/Indianapolis\n\* `America\/Indiana\/Knox` - America\/Indiana\/Knox\n\* `America\/Indiana\/Marengo` - America\/Indiana\/Marengo\n\* `America\/Indiana\/Petersburg` - America\/Indiana\/Petersburg\n\* `America\/Indiana\/Tell_City` - America\/Indiana\/Tell_City\n\* `America\/Indiana\/Vevay` - America\/Indiana\/Vevay\n\* `America\/Indiana\/Vincennes` - America\/Indiana\/Vincennes\n\* `America\/Indiana\/Winamac` - America\/Indiana\/Winamac\n\* `America\/Indianapolis` - America\/Indianapolis\n\* `America\/Inuvik` - America\/Inuvik\n\* `America\/Iqaluit` - America\/Iqaluit\n\* `America\/Jamaica` - America\/Jamaica\n\* `America\/Jujuy` - America\/Jujuy\n\* `America\/Juneau` - America\/Juneau\n\* `America\/Kentucky\/Louisville` - America\/Kentucky\/Louisville\n\* `America\/Kentucky\/Monticello` - America\/Kentucky\/Monticello\n\* `America\/Knox_IN` - America\/Knox_IN\n\* `America\/Kralendijk` - America\/Kralendijk\n\* `America\/La_Paz` - America\/La_Paz\n\* `America\/Lima` - America\/Lima\n\* `America\/Los_Angeles` - America\/Los_Angeles\n\* `America\/Louisville` - America\/Louisville\n\* `America\/Lower_Princes` - America\/Lower_Princes\n\* `America\/Maceio` - America\/Maceio\n\* `America\/Managua` - America\/Managua\n\* `America\/Manaus` - America\/Manaus\n\* `America\/Marigot` - America\/Marigot\n\* `America\/Martinique` - America\/Martinique\n\* `America\/Matamoros` - America\/Matamoros\n\* `America\/Mazatlan` - America\/Mazatlan\n\* `America\/Mendoza` - America\/Mendoza\n\* `America\/Menominee` - America\/Menominee\n\* `America\/Merida` - America\/Merida\n\* `America\/Metlakatla` - America\/Metlakatla\n\* `America\/Mexico_City` - America\/Mexico_City\n\* `America\/Miquelon` - America\/Miquelon\n\* `America\/Moncton` - America\/Moncton\n\* `America\/Monterrey` - America\/Monterrey\n\* `America\/Montevideo` - America\/Montevideo\n\* `America\/Montreal` - America\/Montreal\n\* `America\/Montserrat` - America\/Montserrat\n\* `America\/Nassau` - America\/Nassau\n\* `America\/New_York` - America\/New_York\n\* `America\/Nipigon` - America\/Nipigon\n\* `America\/Nome` - America\/Nome\n\* `America\/Noronha` - America\/Noronha\n\* `America\/North_Dakota\/Beulah` - America\/North_Dakota\/Beulah\n\* `America\/North_Dakota\/Center` - America\/North_Dakota\/Center\n\* `America\/North_Dakota\/New_Salem` - America\/North_Dakota\/New_Salem\n\* `America\/Nuuk` - America\/Nuuk\n\* `America\/Ojinaga` - America\/Ojinaga\n\* `America\/Panama` - America\/Panama\n\* `America\/Pangnirtung` - America\/Pangnirtung\n\* `America\/Paramaribo` - America\/Paramaribo\n\* `America\/Phoenix` - America\/Phoenix\n\* `America\/Port-au-Prince` - America\/Port-au-Prince\n\* `America\/Port_of_Spain` - America\/Port_of_Spain\n\* `America\/Porto_Acre` - America\/Porto_Acre\n\* `America\/Porto_Velho` - America\/Porto_Velho\n\* `America\/Puerto_Rico` - America\/Puerto_Rico\n\* `America\/Punta_Arenas` - America\/Punta_Arenas\n\* `America\/Rainy_River` - America\/Rainy_River\n\* `America\/Rankin_Inlet` - America\/Rankin_Inlet\n\* `America\/Recife` - America\/Recife\n\* `America\/Regina` - America\/Regina\n\* `America\/Resolute` - America\/Resolute\n\* `America\/Rio_Branco` - America\/Rio_Branco\n\* `America\/Rosario` - America\/Rosario\n\* `America\/Santa_Isabel` - America\/Santa_Isabel\n\* `America\/Santarem` - America\/Santarem\n\* `America\/Santiago` - America\/Santiago\n\* `America\/Santo_Domingo` - America\/Santo_Domingo\n\* `America\/Sao_Paulo` - America\/Sao_Paulo\n\* `America\/Scoresbysund` - America\/Scoresbysund\n\* `America\/Shiprock` - America\/Shiprock\n\* `America\/Sitka` - America\/Sitka\n\* `America\/St_Barthelemy` - America\/St_Barthelemy\n\* `America\/St_Johns` - America\/St_Johns\n\* `America\/St_Kitts` - America\/St_Kitts\n\* `America\/St_Lucia` - America\/St_Lucia\n\* `America\/St_Thomas` - America\/St_Thomas\n\* `America\/St_Vincent` - America\/St_Vincent\n\* `America\/Swift_Current` - America\/Swift_Current\n\* `America\/Tegucigalpa` - America\/Tegucigalpa\n\* `America\/Thule` - America\/Thule\n\* `America\/Thunder_Bay` - America\/Thunder_Bay\n\* `America\/Tijuana` - America\/Tijuana\n\* `America\/Toronto` - America\/Toronto\n\* `America\/Tortola` - America\/Tortola\n\* `America\/Vancouver` - America\/Vancouver\n\* `America\/Virgin` - America\/Virgin\n\* `America\/Whitehorse` - America\/Whitehorse\n\* `America\/Winnipeg` - America\/Winnipeg\n\* `America\/Yakutat` - America\/Yakutat\n\* `America\/Yellowknife` - America\/Yellowknife\n\* `Antarctica\/Casey` - Antarctica\/Casey\n\* `Antarctica\/Davis` - Antarctica\/Davis\n\* `Antarctica\/DumontDUrville` - Antarctica\/DumontDUrville\n\* `Antarctica\/Macquarie` - Antarctica\/Macquarie\n\* `Antarctica\/Mawson` - Antarctica\/Mawson\n\* `Antarctica\/McMurdo` - Antarctica\/McMurdo\n\* `Antarctica\/Palmer` - Antarctica\/Palmer\n\* `Antarctica\/Rothera` - Antarctica\/Rothera\n\* `Antarctica\/South_Pole` - Antarctica\/South_Pole\n\* `Antarctica\/Syowa` - Antarctica\/Syowa\n\* `Antarctica\/Troll` - Antarctica\/Troll\n\* `Antarctica\/Vostok` - Antarctica\/Vostok\n\* `Arctic\/Longyearbyen` - Arctic\/Longyearbyen\n\* `Asia\/Aden` - Asia\/Aden\n\* `Asia\/Almaty` - Asia\/Almaty\n\* `Asia\/Amman` - Asia\/Amman\n\* `Asia\/Anadyr` - Asia\/Anadyr\n\* `Asia\/Aqtau` - Asia\/Aqtau\n\* `Asia\/Aqtobe` - Asia\/Aqtobe\n\* `Asia\/Ashgabat` - Asia\/Ashgabat\n\* `Asia\/Ashkhabad` - Asia\/Ashkhabad\n\* `Asia\/Atyrau` - Asia\/Atyrau\n\* `Asia\/Baghdad` - Asia\/Baghdad\n\* `Asia\/Bahrain` - Asia\/Bahrain\n\* `Asia\/Baku` - Asia\/Baku\n\* `Asia\/Bangkok` - Asia\/Bangkok\n\* `Asia\/Barnaul` - Asia\/Barnaul\n\* `Asia\/Beirut` - Asia\/Beirut\n\* `Asia\/Bishkek` - Asia\/Bishkek\n\* `Asia\/Brunei` - Asia\/Brunei\n\* `Asia\/Calcutta` - Asia\/Calcutta\n\* `Asia\/Chita` - Asia\/Chita\n\* `Asia\/Choibalsan` - Asia\/Choibalsan\n\* `Asia\/Chongqing` - Asia\/Chongqing\n\* `Asia\/Chungking` - Asia\/Chungking\n\* `Asia\/Colombo` - Asia\/Colombo\n\* `Asia\/Dacca` - Asia\/Dacca\n\* `Asia\/Damascus` - Asia\/Damascus\n\* `Asia\/Dhaka` - Asia\/Dhaka\n\* `Asia\/Dili` - Asia\/Dili\n\* `Asia\/Dubai` - Asia\/Dubai\n\* `Asia\/Dushanbe` - Asia\/Dushanbe\n\* `Asia\/Famagusta` - Asia\/Famagusta\n\* `Asia\/Gaza` - Asia\/Gaza\n\* `Asia\/Harbin` - Asia\/Harbin\n\* `Asia\/Hebron` - Asia\/Hebron\n\* `Asia\/Ho_Chi_Minh` - Asia\/Ho_Chi_Minh\n\* `Asia\/Hong_Kong` - Asia\/Hong_Kong\n\* `Asia\/Hovd` - Asia\/Hovd\n\* `Asia\/Irkutsk` - Asia\/Irkutsk\n\* `Asia\/Istanbul` - Asia\/Istanbul\n\* `Asia\/Jakarta` - Asia\/Jakarta\n\* `Asia\/Jayapura` - Asia\/Jayapura\n\* `Asia\/Jerusalem` - Asia\/Jerusalem\n\* `Asia\/Kabul` - Asia\/Kabul\n\* `Asia\/Kamchatka` - Asia\/Kamchatka\n\* `Asia\/Karachi` - Asia\/Karachi\n\* `Asia\/Kashgar` - Asia\/Kashgar\n\* `Asia\/Kathmandu` - Asia\/Kathmandu\n\* `Asia\/Katmandu` - Asia\/Katmandu\n\* `Asia\/Khandyga` - Asia\/Khandyga\n\* `Asia\/Kolkata` - Asia\/Kolkata\n\* `Asia\/Krasnoyarsk` - Asia\/Krasnoyarsk\n\* `Asia\/Kuala_Lumpur` - Asia\/Kuala_Lumpur\n\* `Asia\/Kuching` - Asia\/Kuching\n\* `Asia\/Kuwait` - Asia\/Kuwait\n\* `Asia\/Macao` - Asia\/Macao\n\* `Asia\/Macau` - Asia\/Macau\n\* `Asia\/Magadan` - Asia\/Magadan\n\* `Asia\/Makassar` - Asia\/Makassar\n\* `Asia\/Manila` - Asia\/Manila\n\* `Asia\/Muscat` - Asia\/Muscat\n\* `Asia\/Nicosia` - Asia\/Nicosia\n\* `Asia\/Novokuznetsk` - Asia\/Novokuznetsk\n\* `Asia\/Novosibirsk` - Asia\/Novosibirsk\n\* `Asia\/Omsk` - Asia\/Omsk\n\* `Asia\/Oral` - Asia\/Oral\n\* `Asia\/Phnom_Penh` - Asia\/Phnom_Penh\n\* `Asia\/Pontianak` - Asia\/Pontianak\n\* `Asia\/Pyongyang` - Asia\/Pyongyang\n\* `Asia\/Qatar` - Asia\/Qatar\n\* `Asia\/Qostanay` - Asia\/Qostanay\n\* `Asia\/Qyzylorda` - Asia\/Qyzylorda\n\* `Asia\/Rangoon` - Asia\/Rangoon\n\* `Asia\/Riyadh` - Asia\/Riyadh\n\* `Asia\/Saigon` - Asia\/Saigon\n\* `Asia\/Sakhalin` - Asia\/Sakhalin\n\* `Asia\/Samarkand` - Asia\/Samarkand\n\* `Asia\/Seoul` - Asia\/Seoul\n\* `Asia\/Shanghai` - Asia\/Shanghai\n\* `Asia\/Singapore` - Asia\/Singapore\n\* `Asia\/Srednekolymsk` - Asia\/Srednekolymsk\n\* `Asia\/Taipei` - Asia\/Taipei\n\* `Asia\/Tashkent` - Asia\/Tashkent\n\* `Asia\/Tbilisi` - Asia\/Tbilisi\n\* `Asia\/Tehran` - Asia\/Tehran\n\* `Asia\/Tel_Aviv` - Asia\/Tel_Aviv\n\* `Asia\/Thimbu` - Asia\/Thimbu\n\* `Asia\/Thimphu` - Asia\/Thimphu\n\* `Asia\/Tokyo` - Asia\/Tokyo\n\* `Asia\/Tomsk` - Asia\/Tomsk\n\* `Asia\/Ujung_Pandang` - Asia\/Ujung_Pandang\n\* `Asia\/Ulaanbaatar` - Asia\/Ulaanbaatar\n\* `Asia\/Ulan_Bator` - Asia\/Ulan_Bator\n\* `Asia\/Urumqi` - Asia\/Urumqi\n\* `Asia\/Ust-Nera` - Asia\/Ust-Nera\n\* `Asia\/Vientiane` - Asia\/Vientiane\n\* `Asia\/Vladivostok` - Asia\/Vladivostok\n\* `Asia\/Yakutsk` - Asia\/Yakutsk\n\* `Asia\/Yangon` - Asia\/Yangon\n\* `Asia\/Yekaterinburg` - Asia\/Yekaterinburg\n\* `Asia\/Yerevan` - Asia\/Yerevan\n\* `Atlantic\/Azores` - Atlantic\/Azores\n\* `Atlantic\/Bermuda` - Atlantic\/Bermuda\n\* `Atlantic\/Canary` - Atlantic\/Canary\n\* `Atlantic\/Cape_Verde` - Atlantic\/Cape_Verde\n\* `Atlantic\/Faeroe` - Atlantic\/Faeroe\n\* `Atlantic\/Faroe` - Atlantic\/Faroe\n\* `Atlantic\/Jan_Mayen` - Atlantic\/Jan_Mayen\n\* `Atlantic\/Madeira` - Atlantic\/Madeira\n\* `Atlantic\/Reykjavik` - Atlantic\/Reykjavik\n\* `Atlantic\/South_Georgia` - Atlantic\/South_Georgia\n\* `Atlantic\/St_Helena` - Atlantic\/St_Helena\n\* `Atlantic\/Stanley` - Atlantic\/Stanley\n\* `Australia\/ACT` - Australia\/ACT\n\* `Australia\/Adelaide` - Australia\/Adelaide\n\* `Australia\/Brisbane` - Australia\/Brisbane\n\* `Australia\/Broken_Hill` - Australia\/Broken_Hill\n\* `Australia\/Canberra` - Australia\/Canberra\n\* `Australia\/Currie` - Australia\/Currie\n\* `Australia\/Darwin` - Australia\/Darwin\n\* `Australia\/Eucla` - Australia\/Eucla\n\* `Australia\/Hobart` - Australia\/Hobart\n\* `Australia\/LHI` - Australia\/LHI\n\* `Australia\/Lindeman` - Australia\/Lindeman\n\* `Australia\/Lord_Howe` - Australia\/Lord_Howe\n\* `Australia\/Melbourne` - Australia\/Melbourne\n\* `Australia\/NSW` - Australia\/NSW\n\* `Australia\/North` - Australia\/North\n\* `Australia\/Perth` - Australia\/Perth\n\* `Australia\/Queensland` - Australia\/Queensland\n\* `Australia\/South` - Australia\/South\n\* `Australia\/Sydney` - Australia\/Sydney\n\* `Australia\/Tasmania` - Australia\/Tasmania\n\* `Australia\/Victoria` - Australia\/Victoria\n\* `Australia\/West` - Australia\/West\n\* `Australia\/Yancowinna` - Australia\/Yancowinna\n\* `Brazil\/Acre` - Brazil\/Acre\n\* `Brazil\/DeNoronha` - Brazil\/DeNoronha\n\* `Brazil\/East` - Brazil\/East\n\* `Brazil\/West` - Brazil\/West\n\* `CET` - CET\n\* `CST6CDT` - CST6CDT\n\* `Canada\/Atlantic` - Canada\/Atlantic\n\* `Canada\/Central` - Canada\/Central\n\* `Canada\/Eastern` - Canada\/Eastern\n\* `Canada\/Mountain` - Canada\/Mountain\n\* `Canada\/Newfoundland` - Canada\/Newfoundland\n\* `Canada\/Pacific` - Canada\/Pacific\n\* `Canada\/Saskatchewan` - Canada\/Saskatchewan\n\* `Canada\/Yukon` - Canada\/Yukon\n\* `Chile\/Continental` - Chile\/Continental\n\* `Chile\/EasterIsland` - Chile\/EasterIsland\n\* `Cuba` - Cuba\n\* `EET` - EET\n\* `EST` - EST\n\* `EST5EDT` - EST5EDT\n\* `Egypt` - Egypt\n\* `Eire` - Eire\n\* `Etc\/GMT` - Etc\/GMT\n\* `Etc\/GMT+0` - Etc\/GMT+0\n\* `Etc\/GMT+1` - Etc\/GMT+1\n\* `Etc\/GMT+10` - Etc\/GMT+10\n\* `Etc\/GMT+11` - Etc\/GMT+11\n\* `Etc\/GMT+12` - Etc\/GMT+12\n\* `Etc\/GMT+2` - Etc\/GMT+2\n\* `Etc\/GMT+3` - Etc\/GMT+3\n\* `Etc\/GMT+4` - Etc\/GMT+4\n\* `Etc\/GMT+5` - Etc\/GMT+5\n\* `Etc\/GMT+6` - Etc\/GMT+6\n\* `Etc\/GMT+7` - Etc\/GMT+7\n\* `Etc\/GMT+8` - Etc\/GMT+8\n\* `Etc\/GMT+9` - Etc\/GMT+9\n\* `Etc\/GMT-0` - Etc\/GMT-0\n\* `Etc\/GMT-1` - Etc\/GMT-1\n\* `Etc\/GMT-10` - Etc\/GMT-10\n\* `Etc\/GMT-11` - Etc\/GMT-11\n\* `Etc\/GMT-12` - Etc\/GMT-12\n\* `Etc\/GMT-13` - Etc\/GMT-13\n\* `Etc\/GMT-14` - Etc\/GMT-14\n\* `Etc\/GMT-2` - Etc\/GMT-2\n\* `Etc\/GMT-3` - Etc\/GMT-3\n\* `Etc\/GMT-4` - Etc\/GMT-4\n\* `Etc\/GMT-5` - Etc\/GMT-5\n\* `Etc\/GMT-6` - Etc\/GMT-6\n\* `Etc\/GMT-7` - Etc\/GMT-7\n\* `Etc\/GMT-8` - Etc\/GMT-8\n\* `Etc\/GMT-9` - Etc\/GMT-9\n\* `Etc\/GMT0` - Etc\/GMT0\n\* `Etc\/Greenwich` - Etc\/Greenwich\n\* `Etc\/UCT` - Etc\/UCT\n\* `Etc\/UTC` - Etc\/UTC\n\* `Etc\/Universal` - Etc\/Universal\n\* `Etc\/Zulu` - Etc\/Zulu\n\* `Europe\/Amsterdam` - Europe\/Amsterdam\n\* `Europe\/Andorra` - Europe\/Andorra\n\* `Europe\/Astrakhan` - Europe\/Astrakhan\n\* `Europe\/Athens` - Europe\/Athens\n\* `Europe\/Belfast` - Europe\/Belfast\n\* `Europe\/Belgrade` - Europe\/Belgrade\n\* `Europe\/Berlin` - Europe\/Berlin\n\* `Europe\/Bratislava` - Europe\/Bratislava\n\* `Europe\/Brussels` - Europe\/Brussels\n\* `Europe\/Bucharest` - Europe\/Bucharest\n\* `Europe\/Budapest` - Europe\/Budapest\n\* `Europe\/Busingen` - Europe\/Busingen\n\* `Europe\/Chisinau` - Europe\/Chisinau\n\* `Europe\/Copenhagen` - Europe\/Copenhagen\n\* `Europe\/Dublin` - Europe\/Dublin\n\* `Europe\/Gibraltar` - Europe\/Gibraltar\n\* `Europe\/Guernsey` - Europe\/Guernsey\n\* `Europe\/Helsinki` - Europe\/Helsinki\n\* `Europe\/Isle_of_Man` - Europe\/Isle_of_Man\n\* `Europe\/Istanbul` - Europe\/Istanbul\n\* `Europe\/Jersey` - Europe\/Jersey\n\* `Europe\/Kaliningrad` - Europe\/Kaliningrad\n\* `Europe\/Kiev` - Europe\/Kiev\n\* `Europe\/Kirov` - Europe\/Kirov\n\* `Europe\/Kyiv` - Europe\/Kyiv\n\* `Europe\/Lisbon` - Europe\/Lisbon\n\* `Europe\/Ljubljana` - Europe\/Ljubljana\n\* `Europe\/London` - Europe\/London\n\* `Europe\/Luxembourg` - Europe\/Luxembourg\n\* `Europe\/Madrid` - Europe\/Madrid\n\* `Europe\/Malta` - Europe\/Malta\n\* `Europe\/Mariehamn` - Europe\/Mariehamn\n\* `Europe\/Minsk` - Europe\/Minsk\n\* `Europe\/Monaco` - Europe\/Monaco\n\* `Europe\/Moscow` - Europe\/Moscow\n\* `Europe\/Nicosia` - Europe\/Nicosia\n\* `Europe\/Oslo` - Europe\/Oslo\n\* `Europe\/Paris` - Europe\/Paris\n\* `Europe\/Podgorica` - Europe\/Podgorica\n\* `Europe\/Prague` - Europe\/Prague\n\* `Europe\/Riga` - Europe\/Riga\n\* `Europe\/Rome` - Europe\/Rome\n\* `Europe\/Samara` - Europe\/Samara\n\* `Europe\/San_Marino` - Europe\/San_Marino\n\* `Europe\/Sarajevo` - Europe\/Sarajevo\n\* `Europe\/Saratov` - Europe\/Saratov\n\* `Europe\/Simferopol` - Europe\/Simferopol\n\* `Europe\/Skopje` - Europe\/Skopje\n\* `Europe\/Sofia` - Europe\/Sofia\n\* `Europe\/Stockholm` - Europe\/Stockholm\n\* `Europe\/Tallinn` - Europe\/Tallinn\n\* `Europe\/Tirane` - Europe\/Tirane\n\* `Europe\/Tiraspol` - Europe\/Tiraspol\n\* `Europe\/Ulyanovsk` - Europe\/Ulyanovsk\n\* `Europe\/Uzhgorod` - Europe\/Uzhgorod\n\* `Europe\/Vaduz` - Europe\/Vaduz\n\* `Europe\/Vatican` - Europe\/Vatican\n\* `Europe\/Vienna` - Europe\/Vienna\n\* `Europe\/Vilnius` - Europe\/Vilnius\n\* `Europe\/Volgograd` - Europe\/Volgograd\n\* `Europe\/Warsaw` - Europe\/Warsaw\n\* `Europe\/Zagreb` - Europe\/Zagreb\n\* `Europe\/Zaporozhye` - Europe\/Zaporozhye\n\* `Europe\/Zurich` - Europe\/Zurich\n\* `GB` - GB\n\* `GB-Eire` - GB-Eire\n\* `GMT` - GMT\n\* `GMT+0` - GMT+0\n\* `GMT-0` - GMT-0\n\* `GMT0` - GMT0\n\* `Greenwich` - Greenwich\n\* `HST` - HST\n\* `Hongkong` - Hongkong\n\* `Iceland` - Iceland\n\* `Indian\/Antananarivo` - Indian\/Antananarivo\n\* `Indian\/Chagos` - Indian\/Chagos\n\* `Indian\/Christmas` - Indian\/Christmas\n\* `Indian\/Cocos` - Indian\/Cocos\n\* `Indian\/Comoro` - Indian\/Comoro\n\* `Indian\/Kerguelen` - Indian\/Kerguelen\n\* `Indian\/Mahe` - Indian\/Mahe\n\* `Indian\/Maldives` - Indian\/Maldives\n\* `Indian\/Mauritius` - Indian\/Mauritius\n\* `Indian\/Mayotte` - Indian\/Mayotte\n\* `Indian\/Reunion` - Indian\/Reunion\n\* `Iran` - Iran\n\* `Israel` - Israel\n\* `Jamaica` - Jamaica\n\* `Japan` - Japan\n\* `Kwajalein` - Kwajalein\n\* `Libya` - Libya\n\* `MET` - MET\n\* `MST` - MST\n\* `MST7MDT` - MST7MDT\n\* `Mexico\/BajaNorte` - Mexico\/BajaNorte\n\* `Mexico\/BajaSur` - Mexico\/BajaSur\n\* `Mexico\/General` - Mexico\/General\n\* `NZ` - NZ\n\* `NZ-CHAT` - NZ-CHAT\n\* `Navajo` - Navajo\n\* `PRC` - PRC\n\* `PST8PDT` - PST8PDT\n\* `Pacific\/Apia` - Pacific\/Apia\n\* `Pacific\/Auckland` - Pacific\/Auckland\n\* `Pacific\/Bougainville` - Pacific\/Bougainville\n\* `Pacific\/Chatham` - Pacific\/Chatham\n\* `Pacific\/Chuuk` - Pacific\/Chuuk\n\* `Pacific\/Easter` - Pacific\/Easter\n\* `Pacific\/Efate` - Pacific\/Efate\n\* `Pacific\/Enderbury` - Pacific\/Enderbury\n\* `Pacific\/Fakaofo` - Pacific\/Fakaofo\n\* `Pacific\/Fiji` - Pacific\/Fiji\n\* `Pacific\/Funafuti` - Pacific\/Funafuti\n\* `Pacific\/Galapagos` - Pacific\/Galapagos\n\* `Pacific\/Gambier` - Pacific\/Gambier\n\* `Pacific\/Guadalcanal` - Pacific\/Guadalcanal\n\* `Pacific\/Guam` - Pacific\/Guam\n\* `Pacific\/Honolulu` - Pacific\/Honolulu\n\* `Pacific\/Johnston` - Pacific\/Johnston\n\* `Pacific\/Kanton` - Pacific\/Kanton\n\* `Pacific\/Kiritimati` - Pacific\/Kiritimati\n\* `Pacific\/Kosrae` - Pacific\/Kosrae\n\* `Pacific\/Kwajalein` - Pacific\/Kwajalein\n\* `Pacific\/Majuro` - Pacific\/Majuro\n\* `Pacific\/Marquesas` - Pacific\/Marquesas\n\* `Pacific\/Midway` - Pacific\/Midway\n\* `Pacific\/Nauru` - Pacific\/Nauru\n\* `Pacific\/Niue` - Pacific\/Niue\n\* `Pacific\/Norfolk` - Pacific\/Norfolk\n\* `Pacific\/Noumea` - Pacific\/Noumea\n\* `Pacific\/Pago_Pago` - Pacific\/Pago_Pago\n\* `Pacific\/Palau` - Pacific\/Palau\n\* `Pacific\/Pitcairn` - Pacific\/Pitcairn\n\* `Pacific\/Pohnpei` - Pacific\/Pohnpei\n\* `Pacific\/Ponape` - Pacific\/Ponape\n\* `Pacific\/Port_Moresby` - Pacific\/Port_Moresby\n\* `Pacific\/Rarotonga` - Pacific\/Rarotonga\n\* `Pacific\/Saipan` - Pacific\/Saipan\n\* `Pacific\/Samoa` - Pacific\/Samoa\n\* `Pacific\/Tahiti` - Pacific\/Tahiti\n\* `Pacific\/Tarawa` - Pacific\/Tarawa\n\* `Pacific\/Tongatapu` - Pacific\/Tongatapu\n\* `Pacific\/Truk` - Pacific\/Truk\n\* `Pacific\/Wake` - Pacific\/Wake\n\* `Pacific\/Wallis` - Pacific\/Wallis\n\* `Pacific\/Yap` - Pacific\/Yap\n\* `Poland` - Poland\n\* `Portugal` - Portugal\n\* `ROC` - ROC\n\* `ROK` - ROK\n\* `Singapore` - Singapore\n\* `Turkey` - Turkey\n\* `UCT` - UCT\n\* `US\/Alaska` - US\/Alaska\n\* `US\/Aleutian` - US\/Aleutian\n\* `US\/Arizona` - US\/Arizona\n\* `US\/Central` - US\/Central\n\* `US\/East-Indiana` - US\/East-Indiana\n\* `US\/Eastern` - US\/Eastern\n\* `US\/Hawaii` - US\/Hawaii\n\* `US\/Indiana-Starke` - US\/Indiana-Starke\n\* `US\/Michigan` - US\/Michigan\n\* `US\/Mountain` - US\/Mountain\n\* `US\/Pacific` - US\/Pacific\n\* `US\/Samoa` - US\/Samoa\n\* `UTC` - UTC\n\* `Universal` - Universal\n\* `W-SU` - W-SU\n\* `WET` - WET\n\* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(organizationsProjectsCreateBodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat('decimal', organizationsProjectsCreateBodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(organizationsProjectsCreateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(organizationsProjectsCreateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(organizationsProjectsCreateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('\* `0` - Sunday\n\* `1` - Monday'),
                zod.null(),
            ])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n\* `0` - Sunday\n\* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(organizationsProjectsCreateBodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations \/ live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(organizationsProjectsCreateBodyMarketingAnalyticsConfigAttributionWindowDaysMax)
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsCreateBodyDefaultDataThemeMin)
            .max(organizationsProjectsCreateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Replace a project and its settings. Prefer the PATCH endpoint for partial updates — PUT requires every writable field to be provided.
 */
export const organizationsProjectsUpdateBodyNameMax = 200

export const organizationsProjectsUpdateBodyProductDescriptionMax = 1000

export const organizationsProjectsUpdateBodyAppUrlsItemMax = 200

export const organizationsProjectsUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const organizationsProjectsUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsUpdateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsUpdateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsUpdateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod.array(zod.string().max(organizationsProjectsUpdateBodyAppUrlsItemMax).nullable()).optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal\/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal\/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America\/Los_Angeles`).\n\n\* `Africa\/Abidjan` - Africa\/Abidjan\n\* `Africa\/Accra` - Africa\/Accra\n\* `Africa\/Addis_Ababa` - Africa\/Addis_Ababa\n\* `Africa\/Algiers` - Africa\/Algiers\n\* `Africa\/Asmara` - Africa\/Asmara\n\* `Africa\/Asmera` - Africa\/Asmera\n\* `Africa\/Bamako` - Africa\/Bamako\n\* `Africa\/Bangui` - Africa\/Bangui\n\* `Africa\/Banjul` - Africa\/Banjul\n\* `Africa\/Bissau` - Africa\/Bissau\n\* `Africa\/Blantyre` - Africa\/Blantyre\n\* `Africa\/Brazzaville` - Africa\/Brazzaville\n\* `Africa\/Bujumbura` - Africa\/Bujumbura\n\* `Africa\/Cairo` - Africa\/Cairo\n\* `Africa\/Casablanca` - Africa\/Casablanca\n\* `Africa\/Ceuta` - Africa\/Ceuta\n\* `Africa\/Conakry` - Africa\/Conakry\n\* `Africa\/Dakar` - Africa\/Dakar\n\* `Africa\/Dar_es_Salaam` - Africa\/Dar_es_Salaam\n\* `Africa\/Djibouti` - Africa\/Djibouti\n\* `Africa\/Douala` - Africa\/Douala\n\* `Africa\/El_Aaiun` - Africa\/El_Aaiun\n\* `Africa\/Freetown` - Africa\/Freetown\n\* `Africa\/Gaborone` - Africa\/Gaborone\n\* `Africa\/Harare` - Africa\/Harare\n\* `Africa\/Johannesburg` - Africa\/Johannesburg\n\* `Africa\/Juba` - Africa\/Juba\n\* `Africa\/Kampala` - Africa\/Kampala\n\* `Africa\/Khartoum` - Africa\/Khartoum\n\* `Africa\/Kigali` - Africa\/Kigali\n\* `Africa\/Kinshasa` - Africa\/Kinshasa\n\* `Africa\/Lagos` - Africa\/Lagos\n\* `Africa\/Libreville` - Africa\/Libreville\n\* `Africa\/Lome` - Africa\/Lome\n\* `Africa\/Luanda` - Africa\/Luanda\n\* `Africa\/Lubumbashi` - Africa\/Lubumbashi\n\* `Africa\/Lusaka` - Africa\/Lusaka\n\* `Africa\/Malabo` - Africa\/Malabo\n\* `Africa\/Maputo` - Africa\/Maputo\n\* `Africa\/Maseru` - Africa\/Maseru\n\* `Africa\/Mbabane` - Africa\/Mbabane\n\* `Africa\/Mogadishu` - Africa\/Mogadishu\n\* `Africa\/Monrovia` - Africa\/Monrovia\n\* `Africa\/Nairobi` - Africa\/Nairobi\n\* `Africa\/Ndjamena` - Africa\/Ndjamena\n\* `Africa\/Niamey` - Africa\/Niamey\n\* `Africa\/Nouakchott` - Africa\/Nouakchott\n\* `Africa\/Ouagadougou` - Africa\/Ouagadougou\n\* `Africa\/Porto-Novo` - Africa\/Porto-Novo\n\* `Africa\/Sao_Tome` - Africa\/Sao_Tome\n\* `Africa\/Timbuktu` - Africa\/Timbuktu\n\* `Africa\/Tripoli` - Africa\/Tripoli\n\* `Africa\/Tunis` - Africa\/Tunis\n\* `Africa\/Windhoek` - Africa\/Windhoek\n\* `America\/Adak` - America\/Adak\n\* `America\/Anchorage` - America\/Anchorage\n\* `America\/Anguilla` - America\/Anguilla\n\* `America\/Antigua` - America\/Antigua\n\* `America\/Araguaina` - America\/Araguaina\n\* `America\/Argentina\/Buenos_Aires` - America\/Argentina\/Buenos_Aires\n\* `America\/Argentina\/Catamarca` - America\/Argentina\/Catamarca\n\* `America\/Argentina\/ComodRivadavia` - America\/Argentina\/ComodRivadavia\n\* `America\/Argentina\/Cordoba` - America\/Argentina\/Cordoba\n\* `America\/Argentina\/Jujuy` - America\/Argentina\/Jujuy\n\* `America\/Argentina\/La_Rioja` - America\/Argentina\/La_Rioja\n\* `America\/Argentina\/Mendoza` - America\/Argentina\/Mendoza\n\* `America\/Argentina\/Rio_Gallegos` - America\/Argentina\/Rio_Gallegos\n\* `America\/Argentina\/Salta` - America\/Argentina\/Salta\n\* `America\/Argentina\/San_Juan` - America\/Argentina\/San_Juan\n\* `America\/Argentina\/San_Luis` - America\/Argentina\/San_Luis\n\* `America\/Argentina\/Tucuman` - America\/Argentina\/Tucuman\n\* `America\/Argentina\/Ushuaia` - America\/Argentina\/Ushuaia\n\* `America\/Aruba` - America\/Aruba\n\* `America\/Asuncion` - America\/Asuncion\n\* `America\/Atikokan` - America\/Atikokan\n\* `America\/Atka` - America\/Atka\n\* `America\/Bahia` - America\/Bahia\n\* `America\/Bahia_Banderas` - America\/Bahia_Banderas\n\* `America\/Barbados` - America\/Barbados\n\* `America\/Belem` - America\/Belem\n\* `America\/Belize` - America\/Belize\n\* `America\/Blanc-Sablon` - America\/Blanc-Sablon\n\* `America\/Boa_Vista` - America\/Boa_Vista\n\* `America\/Bogota` - America\/Bogota\n\* `America\/Boise` - America\/Boise\n\* `America\/Buenos_Aires` - America\/Buenos_Aires\n\* `America\/Cambridge_Bay` - America\/Cambridge_Bay\n\* `America\/Campo_Grande` - America\/Campo_Grande\n\* `America\/Cancun` - America\/Cancun\n\* `America\/Caracas` - America\/Caracas\n\* `America\/Catamarca` - America\/Catamarca\n\* `America\/Cayenne` - America\/Cayenne\n\* `America\/Cayman` - America\/Cayman\n\* `America\/Chicago` - America\/Chicago\n\* `America\/Chihuahua` - America\/Chihuahua\n\* `America\/Ciudad_Juarez` - America\/Ciudad_Juarez\n\* `America\/Coral_Harbour` - America\/Coral_Harbour\n\* `America\/Cordoba` - America\/Cordoba\n\* `America\/Costa_Rica` - America\/Costa_Rica\n\* `America\/Creston` - America\/Creston\n\* `America\/Cuiaba` - America\/Cuiaba\n\* `America\/Curacao` - America\/Curacao\n\* `America\/Danmarkshavn` - America\/Danmarkshavn\n\* `America\/Dawson` - America\/Dawson\n\* `America\/Dawson_Creek` - America\/Dawson_Creek\n\* `America\/Denver` - America\/Denver\n\* `America\/Detroit` - America\/Detroit\n\* `America\/Dominica` - America\/Dominica\n\* `America\/Edmonton` - America\/Edmonton\n\* `America\/Eirunepe` - America\/Eirunepe\n\* `America\/El_Salvador` - America\/El_Salvador\n\* `America\/Ensenada` - America\/Ensenada\n\* `America\/Fort_Nelson` - America\/Fort_Nelson\n\* `America\/Fort_Wayne` - America\/Fort_Wayne\n\* `America\/Fortaleza` - America\/Fortaleza\n\* `America\/Glace_Bay` - America\/Glace_Bay\n\* `America\/Godthab` - America\/Godthab\n\* `America\/Goose_Bay` - America\/Goose_Bay\n\* `America\/Grand_Turk` - America\/Grand_Turk\n\* `America\/Grenada` - America\/Grenada\n\* `America\/Guadeloupe` - America\/Guadeloupe\n\* `America\/Guatemala` - America\/Guatemala\n\* `America\/Guayaquil` - America\/Guayaquil\n\* `America\/Guyana` - America\/Guyana\n\* `America\/Halifax` - America\/Halifax\n\* `America\/Havana` - America\/Havana\n\* `America\/Hermosillo` - America\/Hermosillo\n\* `America\/Indiana\/Indianapolis` - America\/Indiana\/Indianapolis\n\* `America\/Indiana\/Knox` - America\/Indiana\/Knox\n\* `America\/Indiana\/Marengo` - America\/Indiana\/Marengo\n\* `America\/Indiana\/Petersburg` - America\/Indiana\/Petersburg\n\* `America\/Indiana\/Tell_City` - America\/Indiana\/Tell_City\n\* `America\/Indiana\/Vevay` - America\/Indiana\/Vevay\n\* `America\/Indiana\/Vincennes` - America\/Indiana\/Vincennes\n\* `America\/Indiana\/Winamac` - America\/Indiana\/Winamac\n\* `America\/Indianapolis` - America\/Indianapolis\n\* `America\/Inuvik` - America\/Inuvik\n\* `America\/Iqaluit` - America\/Iqaluit\n\* `America\/Jamaica` - America\/Jamaica\n\* `America\/Jujuy` - America\/Jujuy\n\* `America\/Juneau` - America\/Juneau\n\* `America\/Kentucky\/Louisville` - America\/Kentucky\/Louisville\n\* `America\/Kentucky\/Monticello` - America\/Kentucky\/Monticello\n\* `America\/Knox_IN` - America\/Knox_IN\n\* `America\/Kralendijk` - America\/Kralendijk\n\* `America\/La_Paz` - America\/La_Paz\n\* `America\/Lima` - America\/Lima\n\* `America\/Los_Angeles` - America\/Los_Angeles\n\* `America\/Louisville` - America\/Louisville\n\* `America\/Lower_Princes` - America\/Lower_Princes\n\* `America\/Maceio` - America\/Maceio\n\* `America\/Managua` - America\/Managua\n\* `America\/Manaus` - America\/Manaus\n\* `America\/Marigot` - America\/Marigot\n\* `America\/Martinique` - America\/Martinique\n\* `America\/Matamoros` - America\/Matamoros\n\* `America\/Mazatlan` - America\/Mazatlan\n\* `America\/Mendoza` - America\/Mendoza\n\* `America\/Menominee` - America\/Menominee\n\* `America\/Merida` - America\/Merida\n\* `America\/Metlakatla` - America\/Metlakatla\n\* `America\/Mexico_City` - America\/Mexico_City\n\* `America\/Miquelon` - America\/Miquelon\n\* `America\/Moncton` - America\/Moncton\n\* `America\/Monterrey` - America\/Monterrey\n\* `America\/Montevideo` - America\/Montevideo\n\* `America\/Montreal` - America\/Montreal\n\* `America\/Montserrat` - America\/Montserrat\n\* `America\/Nassau` - America\/Nassau\n\* `America\/New_York` - America\/New_York\n\* `America\/Nipigon` - America\/Nipigon\n\* `America\/Nome` - America\/Nome\n\* `America\/Noronha` - America\/Noronha\n\* `America\/North_Dakota\/Beulah` - America\/North_Dakota\/Beulah\n\* `America\/North_Dakota\/Center` - America\/North_Dakota\/Center\n\* `America\/North_Dakota\/New_Salem` - America\/North_Dakota\/New_Salem\n\* `America\/Nuuk` - America\/Nuuk\n\* `America\/Ojinaga` - America\/Ojinaga\n\* `America\/Panama` - America\/Panama\n\* `America\/Pangnirtung` - America\/Pangnirtung\n\* `America\/Paramaribo` - America\/Paramaribo\n\* `America\/Phoenix` - America\/Phoenix\n\* `America\/Port-au-Prince` - America\/Port-au-Prince\n\* `America\/Port_of_Spain` - America\/Port_of_Spain\n\* `America\/Porto_Acre` - America\/Porto_Acre\n\* `America\/Porto_Velho` - America\/Porto_Velho\n\* `America\/Puerto_Rico` - America\/Puerto_Rico\n\* `America\/Punta_Arenas` - America\/Punta_Arenas\n\* `America\/Rainy_River` - America\/Rainy_River\n\* `America\/Rankin_Inlet` - America\/Rankin_Inlet\n\* `America\/Recife` - America\/Recife\n\* `America\/Regina` - America\/Regina\n\* `America\/Resolute` - America\/Resolute\n\* `America\/Rio_Branco` - America\/Rio_Branco\n\* `America\/Rosario` - America\/Rosario\n\* `America\/Santa_Isabel` - America\/Santa_Isabel\n\* `America\/Santarem` - America\/Santarem\n\* `America\/Santiago` - America\/Santiago\n\* `America\/Santo_Domingo` - America\/Santo_Domingo\n\* `America\/Sao_Paulo` - America\/Sao_Paulo\n\* `America\/Scoresbysund` - America\/Scoresbysund\n\* `America\/Shiprock` - America\/Shiprock\n\* `America\/Sitka` - America\/Sitka\n\* `America\/St_Barthelemy` - America\/St_Barthelemy\n\* `America\/St_Johns` - America\/St_Johns\n\* `America\/St_Kitts` - America\/St_Kitts\n\* `America\/St_Lucia` - America\/St_Lucia\n\* `America\/St_Thomas` - America\/St_Thomas\n\* `America\/St_Vincent` - America\/St_Vincent\n\* `America\/Swift_Current` - America\/Swift_Current\n\* `America\/Tegucigalpa` - America\/Tegucigalpa\n\* `America\/Thule` - America\/Thule\n\* `America\/Thunder_Bay` - America\/Thunder_Bay\n\* `America\/Tijuana` - America\/Tijuana\n\* `America\/Toronto` - America\/Toronto\n\* `America\/Tortola` - America\/Tortola\n\* `America\/Vancouver` - America\/Vancouver\n\* `America\/Virgin` - America\/Virgin\n\* `America\/Whitehorse` - America\/Whitehorse\n\* `America\/Winnipeg` - America\/Winnipeg\n\* `America\/Yakutat` - America\/Yakutat\n\* `America\/Yellowknife` - America\/Yellowknife\n\* `Antarctica\/Casey` - Antarctica\/Casey\n\* `Antarctica\/Davis` - Antarctica\/Davis\n\* `Antarctica\/DumontDUrville` - Antarctica\/DumontDUrville\n\* `Antarctica\/Macquarie` - Antarctica\/Macquarie\n\* `Antarctica\/Mawson` - Antarctica\/Mawson\n\* `Antarctica\/McMurdo` - Antarctica\/McMurdo\n\* `Antarctica\/Palmer` - Antarctica\/Palmer\n\* `Antarctica\/Rothera` - Antarctica\/Rothera\n\* `Antarctica\/South_Pole` - Antarctica\/South_Pole\n\* `Antarctica\/Syowa` - Antarctica\/Syowa\n\* `Antarctica\/Troll` - Antarctica\/Troll\n\* `Antarctica\/Vostok` - Antarctica\/Vostok\n\* `Arctic\/Longyearbyen` - Arctic\/Longyearbyen\n\* `Asia\/Aden` - Asia\/Aden\n\* `Asia\/Almaty` - Asia\/Almaty\n\* `Asia\/Amman` - Asia\/Amman\n\* `Asia\/Anadyr` - Asia\/Anadyr\n\* `Asia\/Aqtau` - Asia\/Aqtau\n\* `Asia\/Aqtobe` - Asia\/Aqtobe\n\* `Asia\/Ashgabat` - Asia\/Ashgabat\n\* `Asia\/Ashkhabad` - Asia\/Ashkhabad\n\* `Asia\/Atyrau` - Asia\/Atyrau\n\* `Asia\/Baghdad` - Asia\/Baghdad\n\* `Asia\/Bahrain` - Asia\/Bahrain\n\* `Asia\/Baku` - Asia\/Baku\n\* `Asia\/Bangkok` - Asia\/Bangkok\n\* `Asia\/Barnaul` - Asia\/Barnaul\n\* `Asia\/Beirut` - Asia\/Beirut\n\* `Asia\/Bishkek` - Asia\/Bishkek\n\* `Asia\/Brunei` - Asia\/Brunei\n\* `Asia\/Calcutta` - Asia\/Calcutta\n\* `Asia\/Chita` - Asia\/Chita\n\* `Asia\/Choibalsan` - Asia\/Choibalsan\n\* `Asia\/Chongqing` - Asia\/Chongqing\n\* `Asia\/Chungking` - Asia\/Chungking\n\* `Asia\/Colombo` - Asia\/Colombo\n\* `Asia\/Dacca` - Asia\/Dacca\n\* `Asia\/Damascus` - Asia\/Damascus\n\* `Asia\/Dhaka` - Asia\/Dhaka\n\* `Asia\/Dili` - Asia\/Dili\n\* `Asia\/Dubai` - Asia\/Dubai\n\* `Asia\/Dushanbe` - Asia\/Dushanbe\n\* `Asia\/Famagusta` - Asia\/Famagusta\n\* `Asia\/Gaza` - Asia\/Gaza\n\* `Asia\/Harbin` - Asia\/Harbin\n\* `Asia\/Hebron` - Asia\/Hebron\n\* `Asia\/Ho_Chi_Minh` - Asia\/Ho_Chi_Minh\n\* `Asia\/Hong_Kong` - Asia\/Hong_Kong\n\* `Asia\/Hovd` - Asia\/Hovd\n\* `Asia\/Irkutsk` - Asia\/Irkutsk\n\* `Asia\/Istanbul` - Asia\/Istanbul\n\* `Asia\/Jakarta` - Asia\/Jakarta\n\* `Asia\/Jayapura` - Asia\/Jayapura\n\* `Asia\/Jerusalem` - Asia\/Jerusalem\n\* `Asia\/Kabul` - Asia\/Kabul\n\* `Asia\/Kamchatka` - Asia\/Kamchatka\n\* `Asia\/Karachi` - Asia\/Karachi\n\* `Asia\/Kashgar` - Asia\/Kashgar\n\* `Asia\/Kathmandu` - Asia\/Kathmandu\n\* `Asia\/Katmandu` - Asia\/Katmandu\n\* `Asia\/Khandyga` - Asia\/Khandyga\n\* `Asia\/Kolkata` - Asia\/Kolkata\n\* `Asia\/Krasnoyarsk` - Asia\/Krasnoyarsk\n\* `Asia\/Kuala_Lumpur` - Asia\/Kuala_Lumpur\n\* `Asia\/Kuching` - Asia\/Kuching\n\* `Asia\/Kuwait` - Asia\/Kuwait\n\* `Asia\/Macao` - Asia\/Macao\n\* `Asia\/Macau` - Asia\/Macau\n\* `Asia\/Magadan` - Asia\/Magadan\n\* `Asia\/Makassar` - Asia\/Makassar\n\* `Asia\/Manila` - Asia\/Manila\n\* `Asia\/Muscat` - Asia\/Muscat\n\* `Asia\/Nicosia` - Asia\/Nicosia\n\* `Asia\/Novokuznetsk` - Asia\/Novokuznetsk\n\* `Asia\/Novosibirsk` - Asia\/Novosibirsk\n\* `Asia\/Omsk` - Asia\/Omsk\n\* `Asia\/Oral` - Asia\/Oral\n\* `Asia\/Phnom_Penh` - Asia\/Phnom_Penh\n\* `Asia\/Pontianak` - Asia\/Pontianak\n\* `Asia\/Pyongyang` - Asia\/Pyongyang\n\* `Asia\/Qatar` - Asia\/Qatar\n\* `Asia\/Qostanay` - Asia\/Qostanay\n\* `Asia\/Qyzylorda` - Asia\/Qyzylorda\n\* `Asia\/Rangoon` - Asia\/Rangoon\n\* `Asia\/Riyadh` - Asia\/Riyadh\n\* `Asia\/Saigon` - Asia\/Saigon\n\* `Asia\/Sakhalin` - Asia\/Sakhalin\n\* `Asia\/Samarkand` - Asia\/Samarkand\n\* `Asia\/Seoul` - Asia\/Seoul\n\* `Asia\/Shanghai` - Asia\/Shanghai\n\* `Asia\/Singapore` - Asia\/Singapore\n\* `Asia\/Srednekolymsk` - Asia\/Srednekolymsk\n\* `Asia\/Taipei` - Asia\/Taipei\n\* `Asia\/Tashkent` - Asia\/Tashkent\n\* `Asia\/Tbilisi` - Asia\/Tbilisi\n\* `Asia\/Tehran` - Asia\/Tehran\n\* `Asia\/Tel_Aviv` - Asia\/Tel_Aviv\n\* `Asia\/Thimbu` - Asia\/Thimbu\n\* `Asia\/Thimphu` - Asia\/Thimphu\n\* `Asia\/Tokyo` - Asia\/Tokyo\n\* `Asia\/Tomsk` - Asia\/Tomsk\n\* `Asia\/Ujung_Pandang` - Asia\/Ujung_Pandang\n\* `Asia\/Ulaanbaatar` - Asia\/Ulaanbaatar\n\* `Asia\/Ulan_Bator` - Asia\/Ulan_Bator\n\* `Asia\/Urumqi` - Asia\/Urumqi\n\* `Asia\/Ust-Nera` - Asia\/Ust-Nera\n\* `Asia\/Vientiane` - Asia\/Vientiane\n\* `Asia\/Vladivostok` - Asia\/Vladivostok\n\* `Asia\/Yakutsk` - Asia\/Yakutsk\n\* `Asia\/Yangon` - Asia\/Yangon\n\* `Asia\/Yekaterinburg` - Asia\/Yekaterinburg\n\* `Asia\/Yerevan` - Asia\/Yerevan\n\* `Atlantic\/Azores` - Atlantic\/Azores\n\* `Atlantic\/Bermuda` - Atlantic\/Bermuda\n\* `Atlantic\/Canary` - Atlantic\/Canary\n\* `Atlantic\/Cape_Verde` - Atlantic\/Cape_Verde\n\* `Atlantic\/Faeroe` - Atlantic\/Faeroe\n\* `Atlantic\/Faroe` - Atlantic\/Faroe\n\* `Atlantic\/Jan_Mayen` - Atlantic\/Jan_Mayen\n\* `Atlantic\/Madeira` - Atlantic\/Madeira\n\* `Atlantic\/Reykjavik` - Atlantic\/Reykjavik\n\* `Atlantic\/South_Georgia` - Atlantic\/South_Georgia\n\* `Atlantic\/St_Helena` - Atlantic\/St_Helena\n\* `Atlantic\/Stanley` - Atlantic\/Stanley\n\* `Australia\/ACT` - Australia\/ACT\n\* `Australia\/Adelaide` - Australia\/Adelaide\n\* `Australia\/Brisbane` - Australia\/Brisbane\n\* `Australia\/Broken_Hill` - Australia\/Broken_Hill\n\* `Australia\/Canberra` - Australia\/Canberra\n\* `Australia\/Currie` - Australia\/Currie\n\* `Australia\/Darwin` - Australia\/Darwin\n\* `Australia\/Eucla` - Australia\/Eucla\n\* `Australia\/Hobart` - Australia\/Hobart\n\* `Australia\/LHI` - Australia\/LHI\n\* `Australia\/Lindeman` - Australia\/Lindeman\n\* `Australia\/Lord_Howe` - Australia\/Lord_Howe\n\* `Australia\/Melbourne` - Australia\/Melbourne\n\* `Australia\/NSW` - Australia\/NSW\n\* `Australia\/North` - Australia\/North\n\* `Australia\/Perth` - Australia\/Perth\n\* `Australia\/Queensland` - Australia\/Queensland\n\* `Australia\/South` - Australia\/South\n\* `Australia\/Sydney` - Australia\/Sydney\n\* `Australia\/Tasmania` - Australia\/Tasmania\n\* `Australia\/Victoria` - Australia\/Victoria\n\* `Australia\/West` - Australia\/West\n\* `Australia\/Yancowinna` - Australia\/Yancowinna\n\* `Brazil\/Acre` - Brazil\/Acre\n\* `Brazil\/DeNoronha` - Brazil\/DeNoronha\n\* `Brazil\/East` - Brazil\/East\n\* `Brazil\/West` - Brazil\/West\n\* `CET` - CET\n\* `CST6CDT` - CST6CDT\n\* `Canada\/Atlantic` - Canada\/Atlantic\n\* `Canada\/Central` - Canada\/Central\n\* `Canada\/Eastern` - Canada\/Eastern\n\* `Canada\/Mountain` - Canada\/Mountain\n\* `Canada\/Newfoundland` - Canada\/Newfoundland\n\* `Canada\/Pacific` - Canada\/Pacific\n\* `Canada\/Saskatchewan` - Canada\/Saskatchewan\n\* `Canada\/Yukon` - Canada\/Yukon\n\* `Chile\/Continental` - Chile\/Continental\n\* `Chile\/EasterIsland` - Chile\/EasterIsland\n\* `Cuba` - Cuba\n\* `EET` - EET\n\* `EST` - EST\n\* `EST5EDT` - EST5EDT\n\* `Egypt` - Egypt\n\* `Eire` - Eire\n\* `Etc\/GMT` - Etc\/GMT\n\* `Etc\/GMT+0` - Etc\/GMT+0\n\* `Etc\/GMT+1` - Etc\/GMT+1\n\* `Etc\/GMT+10` - Etc\/GMT+10\n\* `Etc\/GMT+11` - Etc\/GMT+11\n\* `Etc\/GMT+12` - Etc\/GMT+12\n\* `Etc\/GMT+2` - Etc\/GMT+2\n\* `Etc\/GMT+3` - Etc\/GMT+3\n\* `Etc\/GMT+4` - Etc\/GMT+4\n\* `Etc\/GMT+5` - Etc\/GMT+5\n\* `Etc\/GMT+6` - Etc\/GMT+6\n\* `Etc\/GMT+7` - Etc\/GMT+7\n\* `Etc\/GMT+8` - Etc\/GMT+8\n\* `Etc\/GMT+9` - Etc\/GMT+9\n\* `Etc\/GMT-0` - Etc\/GMT-0\n\* `Etc\/GMT-1` - Etc\/GMT-1\n\* `Etc\/GMT-10` - Etc\/GMT-10\n\* `Etc\/GMT-11` - Etc\/GMT-11\n\* `Etc\/GMT-12` - Etc\/GMT-12\n\* `Etc\/GMT-13` - Etc\/GMT-13\n\* `Etc\/GMT-14` - Etc\/GMT-14\n\* `Etc\/GMT-2` - Etc\/GMT-2\n\* `Etc\/GMT-3` - Etc\/GMT-3\n\* `Etc\/GMT-4` - Etc\/GMT-4\n\* `Etc\/GMT-5` - Etc\/GMT-5\n\* `Etc\/GMT-6` - Etc\/GMT-6\n\* `Etc\/GMT-7` - Etc\/GMT-7\n\* `Etc\/GMT-8` - Etc\/GMT-8\n\* `Etc\/GMT-9` - Etc\/GMT-9\n\* `Etc\/GMT0` - Etc\/GMT0\n\* `Etc\/Greenwich` - Etc\/Greenwich\n\* `Etc\/UCT` - Etc\/UCT\n\* `Etc\/UTC` - Etc\/UTC\n\* `Etc\/Universal` - Etc\/Universal\n\* `Etc\/Zulu` - Etc\/Zulu\n\* `Europe\/Amsterdam` - Europe\/Amsterdam\n\* `Europe\/Andorra` - Europe\/Andorra\n\* `Europe\/Astrakhan` - Europe\/Astrakhan\n\* `Europe\/Athens` - Europe\/Athens\n\* `Europe\/Belfast` - Europe\/Belfast\n\* `Europe\/Belgrade` - Europe\/Belgrade\n\* `Europe\/Berlin` - Europe\/Berlin\n\* `Europe\/Bratislava` - Europe\/Bratislava\n\* `Europe\/Brussels` - Europe\/Brussels\n\* `Europe\/Bucharest` - Europe\/Bucharest\n\* `Europe\/Budapest` - Europe\/Budapest\n\* `Europe\/Busingen` - Europe\/Busingen\n\* `Europe\/Chisinau` - Europe\/Chisinau\n\* `Europe\/Copenhagen` - Europe\/Copenhagen\n\* `Europe\/Dublin` - Europe\/Dublin\n\* `Europe\/Gibraltar` - Europe\/Gibraltar\n\* `Europe\/Guernsey` - Europe\/Guernsey\n\* `Europe\/Helsinki` - Europe\/Helsinki\n\* `Europe\/Isle_of_Man` - Europe\/Isle_of_Man\n\* `Europe\/Istanbul` - Europe\/Istanbul\n\* `Europe\/Jersey` - Europe\/Jersey\n\* `Europe\/Kaliningrad` - Europe\/Kaliningrad\n\* `Europe\/Kiev` - Europe\/Kiev\n\* `Europe\/Kirov` - Europe\/Kirov\n\* `Europe\/Kyiv` - Europe\/Kyiv\n\* `Europe\/Lisbon` - Europe\/Lisbon\n\* `Europe\/Ljubljana` - Europe\/Ljubljana\n\* `Europe\/London` - Europe\/London\n\* `Europe\/Luxembourg` - Europe\/Luxembourg\n\* `Europe\/Madrid` - Europe\/Madrid\n\* `Europe\/Malta` - Europe\/Malta\n\* `Europe\/Mariehamn` - Europe\/Mariehamn\n\* `Europe\/Minsk` - Europe\/Minsk\n\* `Europe\/Monaco` - Europe\/Monaco\n\* `Europe\/Moscow` - Europe\/Moscow\n\* `Europe\/Nicosia` - Europe\/Nicosia\n\* `Europe\/Oslo` - Europe\/Oslo\n\* `Europe\/Paris` - Europe\/Paris\n\* `Europe\/Podgorica` - Europe\/Podgorica\n\* `Europe\/Prague` - Europe\/Prague\n\* `Europe\/Riga` - Europe\/Riga\n\* `Europe\/Rome` - Europe\/Rome\n\* `Europe\/Samara` - Europe\/Samara\n\* `Europe\/San_Marino` - Europe\/San_Marino\n\* `Europe\/Sarajevo` - Europe\/Sarajevo\n\* `Europe\/Saratov` - Europe\/Saratov\n\* `Europe\/Simferopol` - Europe\/Simferopol\n\* `Europe\/Skopje` - Europe\/Skopje\n\* `Europe\/Sofia` - Europe\/Sofia\n\* `Europe\/Stockholm` - Europe\/Stockholm\n\* `Europe\/Tallinn` - Europe\/Tallinn\n\* `Europe\/Tirane` - Europe\/Tirane\n\* `Europe\/Tiraspol` - Europe\/Tiraspol\n\* `Europe\/Ulyanovsk` - Europe\/Ulyanovsk\n\* `Europe\/Uzhgorod` - Europe\/Uzhgorod\n\* `Europe\/Vaduz` - Europe\/Vaduz\n\* `Europe\/Vatican` - Europe\/Vatican\n\* `Europe\/Vienna` - Europe\/Vienna\n\* `Europe\/Vilnius` - Europe\/Vilnius\n\* `Europe\/Volgograd` - Europe\/Volgograd\n\* `Europe\/Warsaw` - Europe\/Warsaw\n\* `Europe\/Zagreb` - Europe\/Zagreb\n\* `Europe\/Zaporozhye` - Europe\/Zaporozhye\n\* `Europe\/Zurich` - Europe\/Zurich\n\* `GB` - GB\n\* `GB-Eire` - GB-Eire\n\* `GMT` - GMT\n\* `GMT+0` - GMT+0\n\* `GMT-0` - GMT-0\n\* `GMT0` - GMT0\n\* `Greenwich` - Greenwich\n\* `HST` - HST\n\* `Hongkong` - Hongkong\n\* `Iceland` - Iceland\n\* `Indian\/Antananarivo` - Indian\/Antananarivo\n\* `Indian\/Chagos` - Indian\/Chagos\n\* `Indian\/Christmas` - Indian\/Christmas\n\* `Indian\/Cocos` - Indian\/Cocos\n\* `Indian\/Comoro` - Indian\/Comoro\n\* `Indian\/Kerguelen` - Indian\/Kerguelen\n\* `Indian\/Mahe` - Indian\/Mahe\n\* `Indian\/Maldives` - Indian\/Maldives\n\* `Indian\/Mauritius` - Indian\/Mauritius\n\* `Indian\/Mayotte` - Indian\/Mayotte\n\* `Indian\/Reunion` - Indian\/Reunion\n\* `Iran` - Iran\n\* `Israel` - Israel\n\* `Jamaica` - Jamaica\n\* `Japan` - Japan\n\* `Kwajalein` - Kwajalein\n\* `Libya` - Libya\n\* `MET` - MET\n\* `MST` - MST\n\* `MST7MDT` - MST7MDT\n\* `Mexico\/BajaNorte` - Mexico\/BajaNorte\n\* `Mexico\/BajaSur` - Mexico\/BajaSur\n\* `Mexico\/General` - Mexico\/General\n\* `NZ` - NZ\n\* `NZ-CHAT` - NZ-CHAT\n\* `Navajo` - Navajo\n\* `PRC` - PRC\n\* `PST8PDT` - PST8PDT\n\* `Pacific\/Apia` - Pacific\/Apia\n\* `Pacific\/Auckland` - Pacific\/Auckland\n\* `Pacific\/Bougainville` - Pacific\/Bougainville\n\* `Pacific\/Chatham` - Pacific\/Chatham\n\* `Pacific\/Chuuk` - Pacific\/Chuuk\n\* `Pacific\/Easter` - Pacific\/Easter\n\* `Pacific\/Efate` - Pacific\/Efate\n\* `Pacific\/Enderbury` - Pacific\/Enderbury\n\* `Pacific\/Fakaofo` - Pacific\/Fakaofo\n\* `Pacific\/Fiji` - Pacific\/Fiji\n\* `Pacific\/Funafuti` - Pacific\/Funafuti\n\* `Pacific\/Galapagos` - Pacific\/Galapagos\n\* `Pacific\/Gambier` - Pacific\/Gambier\n\* `Pacific\/Guadalcanal` - Pacific\/Guadalcanal\n\* `Pacific\/Guam` - Pacific\/Guam\n\* `Pacific\/Honolulu` - Pacific\/Honolulu\n\* `Pacific\/Johnston` - Pacific\/Johnston\n\* `Pacific\/Kanton` - Pacific\/Kanton\n\* `Pacific\/Kiritimati` - Pacific\/Kiritimati\n\* `Pacific\/Kosrae` - Pacific\/Kosrae\n\* `Pacific\/Kwajalein` - Pacific\/Kwajalein\n\* `Pacific\/Majuro` - Pacific\/Majuro\n\* `Pacific\/Marquesas` - Pacific\/Marquesas\n\* `Pacific\/Midway` - Pacific\/Midway\n\* `Pacific\/Nauru` - Pacific\/Nauru\n\* `Pacific\/Niue` - Pacific\/Niue\n\* `Pacific\/Norfolk` - Pacific\/Norfolk\n\* `Pacific\/Noumea` - Pacific\/Noumea\n\* `Pacific\/Pago_Pago` - Pacific\/Pago_Pago\n\* `Pacific\/Palau` - Pacific\/Palau\n\* `Pacific\/Pitcairn` - Pacific\/Pitcairn\n\* `Pacific\/Pohnpei` - Pacific\/Pohnpei\n\* `Pacific\/Ponape` - Pacific\/Ponape\n\* `Pacific\/Port_Moresby` - Pacific\/Port_Moresby\n\* `Pacific\/Rarotonga` - Pacific\/Rarotonga\n\* `Pacific\/Saipan` - Pacific\/Saipan\n\* `Pacific\/Samoa` - Pacific\/Samoa\n\* `Pacific\/Tahiti` - Pacific\/Tahiti\n\* `Pacific\/Tarawa` - Pacific\/Tarawa\n\* `Pacific\/Tongatapu` - Pacific\/Tongatapu\n\* `Pacific\/Truk` - Pacific\/Truk\n\* `Pacific\/Wake` - Pacific\/Wake\n\* `Pacific\/Wallis` - Pacific\/Wallis\n\* `Pacific\/Yap` - Pacific\/Yap\n\* `Poland` - Poland\n\* `Portugal` - Portugal\n\* `ROC` - ROC\n\* `ROK` - ROK\n\* `Singapore` - Singapore\n\* `Turkey` - Turkey\n\* `UCT` - UCT\n\* `US\/Alaska` - US\/Alaska\n\* `US\/Aleutian` - US\/Aleutian\n\* `US\/Arizona` - US\/Arizona\n\* `US\/Central` - US\/Central\n\* `US\/East-Indiana` - US\/East-Indiana\n\* `US\/Eastern` - US\/Eastern\n\* `US\/Hawaii` - US\/Hawaii\n\* `US\/Indiana-Starke` - US\/Indiana-Starke\n\* `US\/Michigan` - US\/Michigan\n\* `US\/Mountain` - US\/Mountain\n\* `US\/Pacific` - US\/Pacific\n\* `US\/Samoa` - US\/Samoa\n\* `UTC` - UTC\n\* `Universal` - Universal\n\* `W-SU` - W-SU\n\* `WET` - WET\n\* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(organizationsProjectsUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat('decimal', organizationsProjectsUpdateBodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(organizationsProjectsUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(organizationsProjectsUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(organizationsProjectsUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('\* `0` - Sunday\n\* `1` - Monday'),
                zod.null(),
            ])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n\* `0` - Sunday\n\* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(organizationsProjectsUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations \/ live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(organizationsProjectsUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax)
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsUpdateBodyDefaultDataThemeMin)
            .max(organizationsProjectsUpdateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Update one or more of a project's settings. Only the fields included in the request body are changed.
 */
export const organizationsProjectsPartialUpdateBodyNameMax = 200

export const organizationsProjectsPartialUpdateBodyProductDescriptionMax = 1000

export const organizationsProjectsPartialUpdateBodyAppUrlsItemMax = 200

export const organizationsProjectsPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const organizationsProjectsPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsPartialUpdateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsPartialUpdateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsPartialUpdateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsPartialUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(zod.string().max(organizationsProjectsPartialUpdateBodyAppUrlsItemMax).nullable())
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal\/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal\/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America\/Los_Angeles`).\n\n\* `Africa\/Abidjan` - Africa\/Abidjan\n\* `Africa\/Accra` - Africa\/Accra\n\* `Africa\/Addis_Ababa` - Africa\/Addis_Ababa\n\* `Africa\/Algiers` - Africa\/Algiers\n\* `Africa\/Asmara` - Africa\/Asmara\n\* `Africa\/Asmera` - Africa\/Asmera\n\* `Africa\/Bamako` - Africa\/Bamako\n\* `Africa\/Bangui` - Africa\/Bangui\n\* `Africa\/Banjul` - Africa\/Banjul\n\* `Africa\/Bissau` - Africa\/Bissau\n\* `Africa\/Blantyre` - Africa\/Blantyre\n\* `Africa\/Brazzaville` - Africa\/Brazzaville\n\* `Africa\/Bujumbura` - Africa\/Bujumbura\n\* `Africa\/Cairo` - Africa\/Cairo\n\* `Africa\/Casablanca` - Africa\/Casablanca\n\* `Africa\/Ceuta` - Africa\/Ceuta\n\* `Africa\/Conakry` - Africa\/Conakry\n\* `Africa\/Dakar` - Africa\/Dakar\n\* `Africa\/Dar_es_Salaam` - Africa\/Dar_es_Salaam\n\* `Africa\/Djibouti` - Africa\/Djibouti\n\* `Africa\/Douala` - Africa\/Douala\n\* `Africa\/El_Aaiun` - Africa\/El_Aaiun\n\* `Africa\/Freetown` - Africa\/Freetown\n\* `Africa\/Gaborone` - Africa\/Gaborone\n\* `Africa\/Harare` - Africa\/Harare\n\* `Africa\/Johannesburg` - Africa\/Johannesburg\n\* `Africa\/Juba` - Africa\/Juba\n\* `Africa\/Kampala` - Africa\/Kampala\n\* `Africa\/Khartoum` - Africa\/Khartoum\n\* `Africa\/Kigali` - Africa\/Kigali\n\* `Africa\/Kinshasa` - Africa\/Kinshasa\n\* `Africa\/Lagos` - Africa\/Lagos\n\* `Africa\/Libreville` - Africa\/Libreville\n\* `Africa\/Lome` - Africa\/Lome\n\* `Africa\/Luanda` - Africa\/Luanda\n\* `Africa\/Lubumbashi` - Africa\/Lubumbashi\n\* `Africa\/Lusaka` - Africa\/Lusaka\n\* `Africa\/Malabo` - Africa\/Malabo\n\* `Africa\/Maputo` - Africa\/Maputo\n\* `Africa\/Maseru` - Africa\/Maseru\n\* `Africa\/Mbabane` - Africa\/Mbabane\n\* `Africa\/Mogadishu` - Africa\/Mogadishu\n\* `Africa\/Monrovia` - Africa\/Monrovia\n\* `Africa\/Nairobi` - Africa\/Nairobi\n\* `Africa\/Ndjamena` - Africa\/Ndjamena\n\* `Africa\/Niamey` - Africa\/Niamey\n\* `Africa\/Nouakchott` - Africa\/Nouakchott\n\* `Africa\/Ouagadougou` - Africa\/Ouagadougou\n\* `Africa\/Porto-Novo` - Africa\/Porto-Novo\n\* `Africa\/Sao_Tome` - Africa\/Sao_Tome\n\* `Africa\/Timbuktu` - Africa\/Timbuktu\n\* `Africa\/Tripoli` - Africa\/Tripoli\n\* `Africa\/Tunis` - Africa\/Tunis\n\* `Africa\/Windhoek` - Africa\/Windhoek\n\* `America\/Adak` - America\/Adak\n\* `America\/Anchorage` - America\/Anchorage\n\* `America\/Anguilla` - America\/Anguilla\n\* `America\/Antigua` - America\/Antigua\n\* `America\/Araguaina` - America\/Araguaina\n\* `America\/Argentina\/Buenos_Aires` - America\/Argentina\/Buenos_Aires\n\* `America\/Argentina\/Catamarca` - America\/Argentina\/Catamarca\n\* `America\/Argentina\/ComodRivadavia` - America\/Argentina\/ComodRivadavia\n\* `America\/Argentina\/Cordoba` - America\/Argentina\/Cordoba\n\* `America\/Argentina\/Jujuy` - America\/Argentina\/Jujuy\n\* `America\/Argentina\/La_Rioja` - America\/Argentina\/La_Rioja\n\* `America\/Argentina\/Mendoza` - America\/Argentina\/Mendoza\n\* `America\/Argentina\/Rio_Gallegos` - America\/Argentina\/Rio_Gallegos\n\* `America\/Argentina\/Salta` - America\/Argentina\/Salta\n\* `America\/Argentina\/San_Juan` - America\/Argentina\/San_Juan\n\* `America\/Argentina\/San_Luis` - America\/Argentina\/San_Luis\n\* `America\/Argentina\/Tucuman` - America\/Argentina\/Tucuman\n\* `America\/Argentina\/Ushuaia` - America\/Argentina\/Ushuaia\n\* `America\/Aruba` - America\/Aruba\n\* `America\/Asuncion` - America\/Asuncion\n\* `America\/Atikokan` - America\/Atikokan\n\* `America\/Atka` - America\/Atka\n\* `America\/Bahia` - America\/Bahia\n\* `America\/Bahia_Banderas` - America\/Bahia_Banderas\n\* `America\/Barbados` - America\/Barbados\n\* `America\/Belem` - America\/Belem\n\* `America\/Belize` - America\/Belize\n\* `America\/Blanc-Sablon` - America\/Blanc-Sablon\n\* `America\/Boa_Vista` - America\/Boa_Vista\n\* `America\/Bogota` - America\/Bogota\n\* `America\/Boise` - America\/Boise\n\* `America\/Buenos_Aires` - America\/Buenos_Aires\n\* `America\/Cambridge_Bay` - America\/Cambridge_Bay\n\* `America\/Campo_Grande` - America\/Campo_Grande\n\* `America\/Cancun` - America\/Cancun\n\* `America\/Caracas` - America\/Caracas\n\* `America\/Catamarca` - America\/Catamarca\n\* `America\/Cayenne` - America\/Cayenne\n\* `America\/Cayman` - America\/Cayman\n\* `America\/Chicago` - America\/Chicago\n\* `America\/Chihuahua` - America\/Chihuahua\n\* `America\/Ciudad_Juarez` - America\/Ciudad_Juarez\n\* `America\/Coral_Harbour` - America\/Coral_Harbour\n\* `America\/Cordoba` - America\/Cordoba\n\* `America\/Costa_Rica` - America\/Costa_Rica\n\* `America\/Creston` - America\/Creston\n\* `America\/Cuiaba` - America\/Cuiaba\n\* `America\/Curacao` - America\/Curacao\n\* `America\/Danmarkshavn` - America\/Danmarkshavn\n\* `America\/Dawson` - America\/Dawson\n\* `America\/Dawson_Creek` - America\/Dawson_Creek\n\* `America\/Denver` - America\/Denver\n\* `America\/Detroit` - America\/Detroit\n\* `America\/Dominica` - America\/Dominica\n\* `America\/Edmonton` - America\/Edmonton\n\* `America\/Eirunepe` - America\/Eirunepe\n\* `America\/El_Salvador` - America\/El_Salvador\n\* `America\/Ensenada` - America\/Ensenada\n\* `America\/Fort_Nelson` - America\/Fort_Nelson\n\* `America\/Fort_Wayne` - America\/Fort_Wayne\n\* `America\/Fortaleza` - America\/Fortaleza\n\* `America\/Glace_Bay` - America\/Glace_Bay\n\* `America\/Godthab` - America\/Godthab\n\* `America\/Goose_Bay` - America\/Goose_Bay\n\* `America\/Grand_Turk` - America\/Grand_Turk\n\* `America\/Grenada` - America\/Grenada\n\* `America\/Guadeloupe` - America\/Guadeloupe\n\* `America\/Guatemala` - America\/Guatemala\n\* `America\/Guayaquil` - America\/Guayaquil\n\* `America\/Guyana` - America\/Guyana\n\* `America\/Halifax` - America\/Halifax\n\* `America\/Havana` - America\/Havana\n\* `America\/Hermosillo` - America\/Hermosillo\n\* `America\/Indiana\/Indianapolis` - America\/Indiana\/Indianapolis\n\* `America\/Indiana\/Knox` - America\/Indiana\/Knox\n\* `America\/Indiana\/Marengo` - America\/Indiana\/Marengo\n\* `America\/Indiana\/Petersburg` - America\/Indiana\/Petersburg\n\* `America\/Indiana\/Tell_City` - America\/Indiana\/Tell_City\n\* `America\/Indiana\/Vevay` - America\/Indiana\/Vevay\n\* `America\/Indiana\/Vincennes` - America\/Indiana\/Vincennes\n\* `America\/Indiana\/Winamac` - America\/Indiana\/Winamac\n\* `America\/Indianapolis` - America\/Indianapolis\n\* `America\/Inuvik` - America\/Inuvik\n\* `America\/Iqaluit` - America\/Iqaluit\n\* `America\/Jamaica` - America\/Jamaica\n\* `America\/Jujuy` - America\/Jujuy\n\* `America\/Juneau` - America\/Juneau\n\* `America\/Kentucky\/Louisville` - America\/Kentucky\/Louisville\n\* `America\/Kentucky\/Monticello` - America\/Kentucky\/Monticello\n\* `America\/Knox_IN` - America\/Knox_IN\n\* `America\/Kralendijk` - America\/Kralendijk\n\* `America\/La_Paz` - America\/La_Paz\n\* `America\/Lima` - America\/Lima\n\* `America\/Los_Angeles` - America\/Los_Angeles\n\* `America\/Louisville` - America\/Louisville\n\* `America\/Lower_Princes` - America\/Lower_Princes\n\* `America\/Maceio` - America\/Maceio\n\* `America\/Managua` - America\/Managua\n\* `America\/Manaus` - America\/Manaus\n\* `America\/Marigot` - America\/Marigot\n\* `America\/Martinique` - America\/Martinique\n\* `America\/Matamoros` - America\/Matamoros\n\* `America\/Mazatlan` - America\/Mazatlan\n\* `America\/Mendoza` - America\/Mendoza\n\* `America\/Menominee` - America\/Menominee\n\* `America\/Merida` - America\/Merida\n\* `America\/Metlakatla` - America\/Metlakatla\n\* `America\/Mexico_City` - America\/Mexico_City\n\* `America\/Miquelon` - America\/Miquelon\n\* `America\/Moncton` - America\/Moncton\n\* `America\/Monterrey` - America\/Monterrey\n\* `America\/Montevideo` - America\/Montevideo\n\* `America\/Montreal` - America\/Montreal\n\* `America\/Montserrat` - America\/Montserrat\n\* `America\/Nassau` - America\/Nassau\n\* `America\/New_York` - America\/New_York\n\* `America\/Nipigon` - America\/Nipigon\n\* `America\/Nome` - America\/Nome\n\* `America\/Noronha` - America\/Noronha\n\* `America\/North_Dakota\/Beulah` - America\/North_Dakota\/Beulah\n\* `America\/North_Dakota\/Center` - America\/North_Dakota\/Center\n\* `America\/North_Dakota\/New_Salem` - America\/North_Dakota\/New_Salem\n\* `America\/Nuuk` - America\/Nuuk\n\* `America\/Ojinaga` - America\/Ojinaga\n\* `America\/Panama` - America\/Panama\n\* `America\/Pangnirtung` - America\/Pangnirtung\n\* `America\/Paramaribo` - America\/Paramaribo\n\* `America\/Phoenix` - America\/Phoenix\n\* `America\/Port-au-Prince` - America\/Port-au-Prince\n\* `America\/Port_of_Spain` - America\/Port_of_Spain\n\* `America\/Porto_Acre` - America\/Porto_Acre\n\* `America\/Porto_Velho` - America\/Porto_Velho\n\* `America\/Puerto_Rico` - America\/Puerto_Rico\n\* `America\/Punta_Arenas` - America\/Punta_Arenas\n\* `America\/Rainy_River` - America\/Rainy_River\n\* `America\/Rankin_Inlet` - America\/Rankin_Inlet\n\* `America\/Recife` - America\/Recife\n\* `America\/Regina` - America\/Regina\n\* `America\/Resolute` - America\/Resolute\n\* `America\/Rio_Branco` - America\/Rio_Branco\n\* `America\/Rosario` - America\/Rosario\n\* `America\/Santa_Isabel` - America\/Santa_Isabel\n\* `America\/Santarem` - America\/Santarem\n\* `America\/Santiago` - America\/Santiago\n\* `America\/Santo_Domingo` - America\/Santo_Domingo\n\* `America\/Sao_Paulo` - America\/Sao_Paulo\n\* `America\/Scoresbysund` - America\/Scoresbysund\n\* `America\/Shiprock` - America\/Shiprock\n\* `America\/Sitka` - America\/Sitka\n\* `America\/St_Barthelemy` - America\/St_Barthelemy\n\* `America\/St_Johns` - America\/St_Johns\n\* `America\/St_Kitts` - America\/St_Kitts\n\* `America\/St_Lucia` - America\/St_Lucia\n\* `America\/St_Thomas` - America\/St_Thomas\n\* `America\/St_Vincent` - America\/St_Vincent\n\* `America\/Swift_Current` - America\/Swift_Current\n\* `America\/Tegucigalpa` - America\/Tegucigalpa\n\* `America\/Thule` - America\/Thule\n\* `America\/Thunder_Bay` - America\/Thunder_Bay\n\* `America\/Tijuana` - America\/Tijuana\n\* `America\/Toronto` - America\/Toronto\n\* `America\/Tortola` - America\/Tortola\n\* `America\/Vancouver` - America\/Vancouver\n\* `America\/Virgin` - America\/Virgin\n\* `America\/Whitehorse` - America\/Whitehorse\n\* `America\/Winnipeg` - America\/Winnipeg\n\* `America\/Yakutat` - America\/Yakutat\n\* `America\/Yellowknife` - America\/Yellowknife\n\* `Antarctica\/Casey` - Antarctica\/Casey\n\* `Antarctica\/Davis` - Antarctica\/Davis\n\* `Antarctica\/DumontDUrville` - Antarctica\/DumontDUrville\n\* `Antarctica\/Macquarie` - Antarctica\/Macquarie\n\* `Antarctica\/Mawson` - Antarctica\/Mawson\n\* `Antarctica\/McMurdo` - Antarctica\/McMurdo\n\* `Antarctica\/Palmer` - Antarctica\/Palmer\n\* `Antarctica\/Rothera` - Antarctica\/Rothera\n\* `Antarctica\/South_Pole` - Antarctica\/South_Pole\n\* `Antarctica\/Syowa` - Antarctica\/Syowa\n\* `Antarctica\/Troll` - Antarctica\/Troll\n\* `Antarctica\/Vostok` - Antarctica\/Vostok\n\* `Arctic\/Longyearbyen` - Arctic\/Longyearbyen\n\* `Asia\/Aden` - Asia\/Aden\n\* `Asia\/Almaty` - Asia\/Almaty\n\* `Asia\/Amman` - Asia\/Amman\n\* `Asia\/Anadyr` - Asia\/Anadyr\n\* `Asia\/Aqtau` - Asia\/Aqtau\n\* `Asia\/Aqtobe` - Asia\/Aqtobe\n\* `Asia\/Ashgabat` - Asia\/Ashgabat\n\* `Asia\/Ashkhabad` - Asia\/Ashkhabad\n\* `Asia\/Atyrau` - Asia\/Atyrau\n\* `Asia\/Baghdad` - Asia\/Baghdad\n\* `Asia\/Bahrain` - Asia\/Bahrain\n\* `Asia\/Baku` - Asia\/Baku\n\* `Asia\/Bangkok` - Asia\/Bangkok\n\* `Asia\/Barnaul` - Asia\/Barnaul\n\* `Asia\/Beirut` - Asia\/Beirut\n\* `Asia\/Bishkek` - Asia\/Bishkek\n\* `Asia\/Brunei` - Asia\/Brunei\n\* `Asia\/Calcutta` - Asia\/Calcutta\n\* `Asia\/Chita` - Asia\/Chita\n\* `Asia\/Choibalsan` - Asia\/Choibalsan\n\* `Asia\/Chongqing` - Asia\/Chongqing\n\* `Asia\/Chungking` - Asia\/Chungking\n\* `Asia\/Colombo` - Asia\/Colombo\n\* `Asia\/Dacca` - Asia\/Dacca\n\* `Asia\/Damascus` - Asia\/Damascus\n\* `Asia\/Dhaka` - Asia\/Dhaka\n\* `Asia\/Dili` - Asia\/Dili\n\* `Asia\/Dubai` - Asia\/Dubai\n\* `Asia\/Dushanbe` - Asia\/Dushanbe\n\* `Asia\/Famagusta` - Asia\/Famagusta\n\* `Asia\/Gaza` - Asia\/Gaza\n\* `Asia\/Harbin` - Asia\/Harbin\n\* `Asia\/Hebron` - Asia\/Hebron\n\* `Asia\/Ho_Chi_Minh` - Asia\/Ho_Chi_Minh\n\* `Asia\/Hong_Kong` - Asia\/Hong_Kong\n\* `Asia\/Hovd` - Asia\/Hovd\n\* `Asia\/Irkutsk` - Asia\/Irkutsk\n\* `Asia\/Istanbul` - Asia\/Istanbul\n\* `Asia\/Jakarta` - Asia\/Jakarta\n\* `Asia\/Jayapura` - Asia\/Jayapura\n\* `Asia\/Jerusalem` - Asia\/Jerusalem\n\* `Asia\/Kabul` - Asia\/Kabul\n\* `Asia\/Kamchatka` - Asia\/Kamchatka\n\* `Asia\/Karachi` - Asia\/Karachi\n\* `Asia\/Kashgar` - Asia\/Kashgar\n\* `Asia\/Kathmandu` - Asia\/Kathmandu\n\* `Asia\/Katmandu` - Asia\/Katmandu\n\* `Asia\/Khandyga` - Asia\/Khandyga\n\* `Asia\/Kolkata` - Asia\/Kolkata\n\* `Asia\/Krasnoyarsk` - Asia\/Krasnoyarsk\n\* `Asia\/Kuala_Lumpur` - Asia\/Kuala_Lumpur\n\* `Asia\/Kuching` - Asia\/Kuching\n\* `Asia\/Kuwait` - Asia\/Kuwait\n\* `Asia\/Macao` - Asia\/Macao\n\* `Asia\/Macau` - Asia\/Macau\n\* `Asia\/Magadan` - Asia\/Magadan\n\* `Asia\/Makassar` - Asia\/Makassar\n\* `Asia\/Manila` - Asia\/Manila\n\* `Asia\/Muscat` - Asia\/Muscat\n\* `Asia\/Nicosia` - Asia\/Nicosia\n\* `Asia\/Novokuznetsk` - Asia\/Novokuznetsk\n\* `Asia\/Novosibirsk` - Asia\/Novosibirsk\n\* `Asia\/Omsk` - Asia\/Omsk\n\* `Asia\/Oral` - Asia\/Oral\n\* `Asia\/Phnom_Penh` - Asia\/Phnom_Penh\n\* `Asia\/Pontianak` - Asia\/Pontianak\n\* `Asia\/Pyongyang` - Asia\/Pyongyang\n\* `Asia\/Qatar` - Asia\/Qatar\n\* `Asia\/Qostanay` - Asia\/Qostanay\n\* `Asia\/Qyzylorda` - Asia\/Qyzylorda\n\* `Asia\/Rangoon` - Asia\/Rangoon\n\* `Asia\/Riyadh` - Asia\/Riyadh\n\* `Asia\/Saigon` - Asia\/Saigon\n\* `Asia\/Sakhalin` - Asia\/Sakhalin\n\* `Asia\/Samarkand` - Asia\/Samarkand\n\* `Asia\/Seoul` - Asia\/Seoul\n\* `Asia\/Shanghai` - Asia\/Shanghai\n\* `Asia\/Singapore` - Asia\/Singapore\n\* `Asia\/Srednekolymsk` - Asia\/Srednekolymsk\n\* `Asia\/Taipei` - Asia\/Taipei\n\* `Asia\/Tashkent` - Asia\/Tashkent\n\* `Asia\/Tbilisi` - Asia\/Tbilisi\n\* `Asia\/Tehran` - Asia\/Tehran\n\* `Asia\/Tel_Aviv` - Asia\/Tel_Aviv\n\* `Asia\/Thimbu` - Asia\/Thimbu\n\* `Asia\/Thimphu` - Asia\/Thimphu\n\* `Asia\/Tokyo` - Asia\/Tokyo\n\* `Asia\/Tomsk` - Asia\/Tomsk\n\* `Asia\/Ujung_Pandang` - Asia\/Ujung_Pandang\n\* `Asia\/Ulaanbaatar` - Asia\/Ulaanbaatar\n\* `Asia\/Ulan_Bator` - Asia\/Ulan_Bator\n\* `Asia\/Urumqi` - Asia\/Urumqi\n\* `Asia\/Ust-Nera` - Asia\/Ust-Nera\n\* `Asia\/Vientiane` - Asia\/Vientiane\n\* `Asia\/Vladivostok` - Asia\/Vladivostok\n\* `Asia\/Yakutsk` - Asia\/Yakutsk\n\* `Asia\/Yangon` - Asia\/Yangon\n\* `Asia\/Yekaterinburg` - Asia\/Yekaterinburg\n\* `Asia\/Yerevan` - Asia\/Yerevan\n\* `Atlantic\/Azores` - Atlantic\/Azores\n\* `Atlantic\/Bermuda` - Atlantic\/Bermuda\n\* `Atlantic\/Canary` - Atlantic\/Canary\n\* `Atlantic\/Cape_Verde` - Atlantic\/Cape_Verde\n\* `Atlantic\/Faeroe` - Atlantic\/Faeroe\n\* `Atlantic\/Faroe` - Atlantic\/Faroe\n\* `Atlantic\/Jan_Mayen` - Atlantic\/Jan_Mayen\n\* `Atlantic\/Madeira` - Atlantic\/Madeira\n\* `Atlantic\/Reykjavik` - Atlantic\/Reykjavik\n\* `Atlantic\/South_Georgia` - Atlantic\/South_Georgia\n\* `Atlantic\/St_Helena` - Atlantic\/St_Helena\n\* `Atlantic\/Stanley` - Atlantic\/Stanley\n\* `Australia\/ACT` - Australia\/ACT\n\* `Australia\/Adelaide` - Australia\/Adelaide\n\* `Australia\/Brisbane` - Australia\/Brisbane\n\* `Australia\/Broken_Hill` - Australia\/Broken_Hill\n\* `Australia\/Canberra` - Australia\/Canberra\n\* `Australia\/Currie` - Australia\/Currie\n\* `Australia\/Darwin` - Australia\/Darwin\n\* `Australia\/Eucla` - Australia\/Eucla\n\* `Australia\/Hobart` - Australia\/Hobart\n\* `Australia\/LHI` - Australia\/LHI\n\* `Australia\/Lindeman` - Australia\/Lindeman\n\* `Australia\/Lord_Howe` - Australia\/Lord_Howe\n\* `Australia\/Melbourne` - Australia\/Melbourne\n\* `Australia\/NSW` - Australia\/NSW\n\* `Australia\/North` - Australia\/North\n\* `Australia\/Perth` - Australia\/Perth\n\* `Australia\/Queensland` - Australia\/Queensland\n\* `Australia\/South` - Australia\/South\n\* `Australia\/Sydney` - Australia\/Sydney\n\* `Australia\/Tasmania` - Australia\/Tasmania\n\* `Australia\/Victoria` - Australia\/Victoria\n\* `Australia\/West` - Australia\/West\n\* `Australia\/Yancowinna` - Australia\/Yancowinna\n\* `Brazil\/Acre` - Brazil\/Acre\n\* `Brazil\/DeNoronha` - Brazil\/DeNoronha\n\* `Brazil\/East` - Brazil\/East\n\* `Brazil\/West` - Brazil\/West\n\* `CET` - CET\n\* `CST6CDT` - CST6CDT\n\* `Canada\/Atlantic` - Canada\/Atlantic\n\* `Canada\/Central` - Canada\/Central\n\* `Canada\/Eastern` - Canada\/Eastern\n\* `Canada\/Mountain` - Canada\/Mountain\n\* `Canada\/Newfoundland` - Canada\/Newfoundland\n\* `Canada\/Pacific` - Canada\/Pacific\n\* `Canada\/Saskatchewan` - Canada\/Saskatchewan\n\* `Canada\/Yukon` - Canada\/Yukon\n\* `Chile\/Continental` - Chile\/Continental\n\* `Chile\/EasterIsland` - Chile\/EasterIsland\n\* `Cuba` - Cuba\n\* `EET` - EET\n\* `EST` - EST\n\* `EST5EDT` - EST5EDT\n\* `Egypt` - Egypt\n\* `Eire` - Eire\n\* `Etc\/GMT` - Etc\/GMT\n\* `Etc\/GMT+0` - Etc\/GMT+0\n\* `Etc\/GMT+1` - Etc\/GMT+1\n\* `Etc\/GMT+10` - Etc\/GMT+10\n\* `Etc\/GMT+11` - Etc\/GMT+11\n\* `Etc\/GMT+12` - Etc\/GMT+12\n\* `Etc\/GMT+2` - Etc\/GMT+2\n\* `Etc\/GMT+3` - Etc\/GMT+3\n\* `Etc\/GMT+4` - Etc\/GMT+4\n\* `Etc\/GMT+5` - Etc\/GMT+5\n\* `Etc\/GMT+6` - Etc\/GMT+6\n\* `Etc\/GMT+7` - Etc\/GMT+7\n\* `Etc\/GMT+8` - Etc\/GMT+8\n\* `Etc\/GMT+9` - Etc\/GMT+9\n\* `Etc\/GMT-0` - Etc\/GMT-0\n\* `Etc\/GMT-1` - Etc\/GMT-1\n\* `Etc\/GMT-10` - Etc\/GMT-10\n\* `Etc\/GMT-11` - Etc\/GMT-11\n\* `Etc\/GMT-12` - Etc\/GMT-12\n\* `Etc\/GMT-13` - Etc\/GMT-13\n\* `Etc\/GMT-14` - Etc\/GMT-14\n\* `Etc\/GMT-2` - Etc\/GMT-2\n\* `Etc\/GMT-3` - Etc\/GMT-3\n\* `Etc\/GMT-4` - Etc\/GMT-4\n\* `Etc\/GMT-5` - Etc\/GMT-5\n\* `Etc\/GMT-6` - Etc\/GMT-6\n\* `Etc\/GMT-7` - Etc\/GMT-7\n\* `Etc\/GMT-8` - Etc\/GMT-8\n\* `Etc\/GMT-9` - Etc\/GMT-9\n\* `Etc\/GMT0` - Etc\/GMT0\n\* `Etc\/Greenwich` - Etc\/Greenwich\n\* `Etc\/UCT` - Etc\/UCT\n\* `Etc\/UTC` - Etc\/UTC\n\* `Etc\/Universal` - Etc\/Universal\n\* `Etc\/Zulu` - Etc\/Zulu\n\* `Europe\/Amsterdam` - Europe\/Amsterdam\n\* `Europe\/Andorra` - Europe\/Andorra\n\* `Europe\/Astrakhan` - Europe\/Astrakhan\n\* `Europe\/Athens` - Europe\/Athens\n\* `Europe\/Belfast` - Europe\/Belfast\n\* `Europe\/Belgrade` - Europe\/Belgrade\n\* `Europe\/Berlin` - Europe\/Berlin\n\* `Europe\/Bratislava` - Europe\/Bratislava\n\* `Europe\/Brussels` - Europe\/Brussels\n\* `Europe\/Bucharest` - Europe\/Bucharest\n\* `Europe\/Budapest` - Europe\/Budapest\n\* `Europe\/Busingen` - Europe\/Busingen\n\* `Europe\/Chisinau` - Europe\/Chisinau\n\* `Europe\/Copenhagen` - Europe\/Copenhagen\n\* `Europe\/Dublin` - Europe\/Dublin\n\* `Europe\/Gibraltar` - Europe\/Gibraltar\n\* `Europe\/Guernsey` - Europe\/Guernsey\n\* `Europe\/Helsinki` - Europe\/Helsinki\n\* `Europe\/Isle_of_Man` - Europe\/Isle_of_Man\n\* `Europe\/Istanbul` - Europe\/Istanbul\n\* `Europe\/Jersey` - Europe\/Jersey\n\* `Europe\/Kaliningrad` - Europe\/Kaliningrad\n\* `Europe\/Kiev` - Europe\/Kiev\n\* `Europe\/Kirov` - Europe\/Kirov\n\* `Europe\/Kyiv` - Europe\/Kyiv\n\* `Europe\/Lisbon` - Europe\/Lisbon\n\* `Europe\/Ljubljana` - Europe\/Ljubljana\n\* `Europe\/London` - Europe\/London\n\* `Europe\/Luxembourg` - Europe\/Luxembourg\n\* `Europe\/Madrid` - Europe\/Madrid\n\* `Europe\/Malta` - Europe\/Malta\n\* `Europe\/Mariehamn` - Europe\/Mariehamn\n\* `Europe\/Minsk` - Europe\/Minsk\n\* `Europe\/Monaco` - Europe\/Monaco\n\* `Europe\/Moscow` - Europe\/Moscow\n\* `Europe\/Nicosia` - Europe\/Nicosia\n\* `Europe\/Oslo` - Europe\/Oslo\n\* `Europe\/Paris` - Europe\/Paris\n\* `Europe\/Podgorica` - Europe\/Podgorica\n\* `Europe\/Prague` - Europe\/Prague\n\* `Europe\/Riga` - Europe\/Riga\n\* `Europe\/Rome` - Europe\/Rome\n\* `Europe\/Samara` - Europe\/Samara\n\* `Europe\/San_Marino` - Europe\/San_Marino\n\* `Europe\/Sarajevo` - Europe\/Sarajevo\n\* `Europe\/Saratov` - Europe\/Saratov\n\* `Europe\/Simferopol` - Europe\/Simferopol\n\* `Europe\/Skopje` - Europe\/Skopje\n\* `Europe\/Sofia` - Europe\/Sofia\n\* `Europe\/Stockholm` - Europe\/Stockholm\n\* `Europe\/Tallinn` - Europe\/Tallinn\n\* `Europe\/Tirane` - Europe\/Tirane\n\* `Europe\/Tiraspol` - Europe\/Tiraspol\n\* `Europe\/Ulyanovsk` - Europe\/Ulyanovsk\n\* `Europe\/Uzhgorod` - Europe\/Uzhgorod\n\* `Europe\/Vaduz` - Europe\/Vaduz\n\* `Europe\/Vatican` - Europe\/Vatican\n\* `Europe\/Vienna` - Europe\/Vienna\n\* `Europe\/Vilnius` - Europe\/Vilnius\n\* `Europe\/Volgograd` - Europe\/Volgograd\n\* `Europe\/Warsaw` - Europe\/Warsaw\n\* `Europe\/Zagreb` - Europe\/Zagreb\n\* `Europe\/Zaporozhye` - Europe\/Zaporozhye\n\* `Europe\/Zurich` - Europe\/Zurich\n\* `GB` - GB\n\* `GB-Eire` - GB-Eire\n\* `GMT` - GMT\n\* `GMT+0` - GMT+0\n\* `GMT-0` - GMT-0\n\* `GMT0` - GMT0\n\* `Greenwich` - Greenwich\n\* `HST` - HST\n\* `Hongkong` - Hongkong\n\* `Iceland` - Iceland\n\* `Indian\/Antananarivo` - Indian\/Antananarivo\n\* `Indian\/Chagos` - Indian\/Chagos\n\* `Indian\/Christmas` - Indian\/Christmas\n\* `Indian\/Cocos` - Indian\/Cocos\n\* `Indian\/Comoro` - Indian\/Comoro\n\* `Indian\/Kerguelen` - Indian\/Kerguelen\n\* `Indian\/Mahe` - Indian\/Mahe\n\* `Indian\/Maldives` - Indian\/Maldives\n\* `Indian\/Mauritius` - Indian\/Mauritius\n\* `Indian\/Mayotte` - Indian\/Mayotte\n\* `Indian\/Reunion` - Indian\/Reunion\n\* `Iran` - Iran\n\* `Israel` - Israel\n\* `Jamaica` - Jamaica\n\* `Japan` - Japan\n\* `Kwajalein` - Kwajalein\n\* `Libya` - Libya\n\* `MET` - MET\n\* `MST` - MST\n\* `MST7MDT` - MST7MDT\n\* `Mexico\/BajaNorte` - Mexico\/BajaNorte\n\* `Mexico\/BajaSur` - Mexico\/BajaSur\n\* `Mexico\/General` - Mexico\/General\n\* `NZ` - NZ\n\* `NZ-CHAT` - NZ-CHAT\n\* `Navajo` - Navajo\n\* `PRC` - PRC\n\* `PST8PDT` - PST8PDT\n\* `Pacific\/Apia` - Pacific\/Apia\n\* `Pacific\/Auckland` - Pacific\/Auckland\n\* `Pacific\/Bougainville` - Pacific\/Bougainville\n\* `Pacific\/Chatham` - Pacific\/Chatham\n\* `Pacific\/Chuuk` - Pacific\/Chuuk\n\* `Pacific\/Easter` - Pacific\/Easter\n\* `Pacific\/Efate` - Pacific\/Efate\n\* `Pacific\/Enderbury` - Pacific\/Enderbury\n\* `Pacific\/Fakaofo` - Pacific\/Fakaofo\n\* `Pacific\/Fiji` - Pacific\/Fiji\n\* `Pacific\/Funafuti` - Pacific\/Funafuti\n\* `Pacific\/Galapagos` - Pacific\/Galapagos\n\* `Pacific\/Gambier` - Pacific\/Gambier\n\* `Pacific\/Guadalcanal` - Pacific\/Guadalcanal\n\* `Pacific\/Guam` - Pacific\/Guam\n\* `Pacific\/Honolulu` - Pacific\/Honolulu\n\* `Pacific\/Johnston` - Pacific\/Johnston\n\* `Pacific\/Kanton` - Pacific\/Kanton\n\* `Pacific\/Kiritimati` - Pacific\/Kiritimati\n\* `Pacific\/Kosrae` - Pacific\/Kosrae\n\* `Pacific\/Kwajalein` - Pacific\/Kwajalein\n\* `Pacific\/Majuro` - Pacific\/Majuro\n\* `Pacific\/Marquesas` - Pacific\/Marquesas\n\* `Pacific\/Midway` - Pacific\/Midway\n\* `Pacific\/Nauru` - Pacific\/Nauru\n\* `Pacific\/Niue` - Pacific\/Niue\n\* `Pacific\/Norfolk` - Pacific\/Norfolk\n\* `Pacific\/Noumea` - Pacific\/Noumea\n\* `Pacific\/Pago_Pago` - Pacific\/Pago_Pago\n\* `Pacific\/Palau` - Pacific\/Palau\n\* `Pacific\/Pitcairn` - Pacific\/Pitcairn\n\* `Pacific\/Pohnpei` - Pacific\/Pohnpei\n\* `Pacific\/Ponape` - Pacific\/Ponape\n\* `Pacific\/Port_Moresby` - Pacific\/Port_Moresby\n\* `Pacific\/Rarotonga` - Pacific\/Rarotonga\n\* `Pacific\/Saipan` - Pacific\/Saipan\n\* `Pacific\/Samoa` - Pacific\/Samoa\n\* `Pacific\/Tahiti` - Pacific\/Tahiti\n\* `Pacific\/Tarawa` - Pacific\/Tarawa\n\* `Pacific\/Tongatapu` - Pacific\/Tongatapu\n\* `Pacific\/Truk` - Pacific\/Truk\n\* `Pacific\/Wake` - Pacific\/Wake\n\* `Pacific\/Wallis` - Pacific\/Wallis\n\* `Pacific\/Yap` - Pacific\/Yap\n\* `Poland` - Poland\n\* `Portugal` - Portugal\n\* `ROC` - ROC\n\* `ROK` - ROK\n\* `Singapore` - Singapore\n\* `Turkey` - Turkey\n\* `UCT` - UCT\n\* `US\/Alaska` - US\/Alaska\n\* `US\/Aleutian` - US\/Aleutian\n\* `US\/Arizona` - US\/Arizona\n\* `US\/Central` - US\/Central\n\* `US\/East-Indiana` - US\/East-Indiana\n\* `US\/Eastern` - US\/Eastern\n\* `US\/Hawaii` - US\/Hawaii\n\* `US\/Indiana-Starke` - US\/Indiana-Starke\n\* `US\/Michigan` - US\/Michigan\n\* `US\/Mountain` - US\/Mountain\n\* `US\/Pacific` - US\/Pacific\n\* `US\/Samoa` - US\/Samoa\n\* `UTC` - UTC\n\* `Universal` - Universal\n\* `W-SU` - W-SU\n\* `WET` - WET\n\* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(organizationsProjectsPartialUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat('decimal', organizationsProjectsPartialUpdateBodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(organizationsProjectsPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(organizationsProjectsPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(organizationsProjectsPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('\* `0` - Sunday\n\* `1` - Monday'),
                zod.null(),
            ])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n\* `0` - Sunday\n\* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(organizationsProjectsPartialUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations \/ live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(organizationsProjectsPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax)
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsPartialUpdateBodyDefaultDataThemeMin)
            .max(organizationsProjectsPartialUpdateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Projects for the current organization.
 */
export const organizationsProjectsAddProductIntentPartialUpdateBodyNameMax = 200

export const organizationsProjectsAddProductIntentPartialUpdateBodyProductDescriptionMax = 1000

export const organizationsProjectsAddProductIntentPartialUpdateBodyAppUrlsItemMax = 200

export const organizationsProjectsAddProductIntentPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsAddProductIntentPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const organizationsProjectsAddProductIntentPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsAddProductIntentPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsAddProductIntentPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsAddProductIntentPartialUpdateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsAddProductIntentPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsAddProductIntentPartialUpdateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsAddProductIntentPartialUpdateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsAddProductIntentPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsAddProductIntentPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsAddProductIntentPartialUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(zod.string().max(organizationsProjectsAddProductIntentPartialUpdateBodyAppUrlsItemMax).nullable())
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal\/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal\/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America\/Los_Angeles`).\n\n\* `Africa\/Abidjan` - Africa\/Abidjan\n\* `Africa\/Accra` - Africa\/Accra\n\* `Africa\/Addis_Ababa` - Africa\/Addis_Ababa\n\* `Africa\/Algiers` - Africa\/Algiers\n\* `Africa\/Asmara` - Africa\/Asmara\n\* `Africa\/Asmera` - Africa\/Asmera\n\* `Africa\/Bamako` - Africa\/Bamako\n\* `Africa\/Bangui` - Africa\/Bangui\n\* `Africa\/Banjul` - Africa\/Banjul\n\* `Africa\/Bissau` - Africa\/Bissau\n\* `Africa\/Blantyre` - Africa\/Blantyre\n\* `Africa\/Brazzaville` - Africa\/Brazzaville\n\* `Africa\/Bujumbura` - Africa\/Bujumbura\n\* `Africa\/Cairo` - Africa\/Cairo\n\* `Africa\/Casablanca` - Africa\/Casablanca\n\* `Africa\/Ceuta` - Africa\/Ceuta\n\* `Africa\/Conakry` - Africa\/Conakry\n\* `Africa\/Dakar` - Africa\/Dakar\n\* `Africa\/Dar_es_Salaam` - Africa\/Dar_es_Salaam\n\* `Africa\/Djibouti` - Africa\/Djibouti\n\* `Africa\/Douala` - Africa\/Douala\n\* `Africa\/El_Aaiun` - Africa\/El_Aaiun\n\* `Africa\/Freetown` - Africa\/Freetown\n\* `Africa\/Gaborone` - Africa\/Gaborone\n\* `Africa\/Harare` - Africa\/Harare\n\* `Africa\/Johannesburg` - Africa\/Johannesburg\n\* `Africa\/Juba` - Africa\/Juba\n\* `Africa\/Kampala` - Africa\/Kampala\n\* `Africa\/Khartoum` - Africa\/Khartoum\n\* `Africa\/Kigali` - Africa\/Kigali\n\* `Africa\/Kinshasa` - Africa\/Kinshasa\n\* `Africa\/Lagos` - Africa\/Lagos\n\* `Africa\/Libreville` - Africa\/Libreville\n\* `Africa\/Lome` - Africa\/Lome\n\* `Africa\/Luanda` - Africa\/Luanda\n\* `Africa\/Lubumbashi` - Africa\/Lubumbashi\n\* `Africa\/Lusaka` - Africa\/Lusaka\n\* `Africa\/Malabo` - Africa\/Malabo\n\* `Africa\/Maputo` - Africa\/Maputo\n\* `Africa\/Maseru` - Africa\/Maseru\n\* `Africa\/Mbabane` - Africa\/Mbabane\n\* `Africa\/Mogadishu` - Africa\/Mogadishu\n\* `Africa\/Monrovia` - Africa\/Monrovia\n\* `Africa\/Nairobi` - Africa\/Nairobi\n\* `Africa\/Ndjamena` - Africa\/Ndjamena\n\* `Africa\/Niamey` - Africa\/Niamey\n\* `Africa\/Nouakchott` - Africa\/Nouakchott\n\* `Africa\/Ouagadougou` - Africa\/Ouagadougou\n\* `Africa\/Porto-Novo` - Africa\/Porto-Novo\n\* `Africa\/Sao_Tome` - Africa\/Sao_Tome\n\* `Africa\/Timbuktu` - Africa\/Timbuktu\n\* `Africa\/Tripoli` - Africa\/Tripoli\n\* `Africa\/Tunis` - Africa\/Tunis\n\* `Africa\/Windhoek` - Africa\/Windhoek\n\* `America\/Adak` - America\/Adak\n\* `America\/Anchorage` - America\/Anchorage\n\* `America\/Anguilla` - America\/Anguilla\n\* `America\/Antigua` - America\/Antigua\n\* `America\/Araguaina` - America\/Araguaina\n\* `America\/Argentina\/Buenos_Aires` - America\/Argentina\/Buenos_Aires\n\* `America\/Argentina\/Catamarca` - America\/Argentina\/Catamarca\n\* `America\/Argentina\/ComodRivadavia` - America\/Argentina\/ComodRivadavia\n\* `America\/Argentina\/Cordoba` - America\/Argentina\/Cordoba\n\* `America\/Argentina\/Jujuy` - America\/Argentina\/Jujuy\n\* `America\/Argentina\/La_Rioja` - America\/Argentina\/La_Rioja\n\* `America\/Argentina\/Mendoza` - America\/Argentina\/Mendoza\n\* `America\/Argentina\/Rio_Gallegos` - America\/Argentina\/Rio_Gallegos\n\* `America\/Argentina\/Salta` - America\/Argentina\/Salta\n\* `America\/Argentina\/San_Juan` - America\/Argentina\/San_Juan\n\* `America\/Argentina\/San_Luis` - America\/Argentina\/San_Luis\n\* `America\/Argentina\/Tucuman` - America\/Argentina\/Tucuman\n\* `America\/Argentina\/Ushuaia` - America\/Argentina\/Ushuaia\n\* `America\/Aruba` - America\/Aruba\n\* `America\/Asuncion` - America\/Asuncion\n\* `America\/Atikokan` - America\/Atikokan\n\* `America\/Atka` - America\/Atka\n\* `America\/Bahia` - America\/Bahia\n\* `America\/Bahia_Banderas` - America\/Bahia_Banderas\n\* `America\/Barbados` - America\/Barbados\n\* `America\/Belem` - America\/Belem\n\* `America\/Belize` - America\/Belize\n\* `America\/Blanc-Sablon` - America\/Blanc-Sablon\n\* `America\/Boa_Vista` - America\/Boa_Vista\n\* `America\/Bogota` - America\/Bogota\n\* `America\/Boise` - America\/Boise\n\* `America\/Buenos_Aires` - America\/Buenos_Aires\n\* `America\/Cambridge_Bay` - America\/Cambridge_Bay\n\* `America\/Campo_Grande` - America\/Campo_Grande\n\* `America\/Cancun` - America\/Cancun\n\* `America\/Caracas` - America\/Caracas\n\* `America\/Catamarca` - America\/Catamarca\n\* `America\/Cayenne` - America\/Cayenne\n\* `America\/Cayman` - America\/Cayman\n\* `America\/Chicago` - America\/Chicago\n\* `America\/Chihuahua` - America\/Chihuahua\n\* `America\/Ciudad_Juarez` - America\/Ciudad_Juarez\n\* `America\/Coral_Harbour` - America\/Coral_Harbour\n\* `America\/Cordoba` - America\/Cordoba\n\* `America\/Costa_Rica` - America\/Costa_Rica\n\* `America\/Creston` - America\/Creston\n\* `America\/Cuiaba` - America\/Cuiaba\n\* `America\/Curacao` - America\/Curacao\n\* `America\/Danmarkshavn` - America\/Danmarkshavn\n\* `America\/Dawson` - America\/Dawson\n\* `America\/Dawson_Creek` - America\/Dawson_Creek\n\* `America\/Denver` - America\/Denver\n\* `America\/Detroit` - America\/Detroit\n\* `America\/Dominica` - America\/Dominica\n\* `America\/Edmonton` - America\/Edmonton\n\* `America\/Eirunepe` - America\/Eirunepe\n\* `America\/El_Salvador` - America\/El_Salvador\n\* `America\/Ensenada` - America\/Ensenada\n\* `America\/Fort_Nelson` - America\/Fort_Nelson\n\* `America\/Fort_Wayne` - America\/Fort_Wayne\n\* `America\/Fortaleza` - America\/Fortaleza\n\* `America\/Glace_Bay` - America\/Glace_Bay\n\* `America\/Godthab` - America\/Godthab\n\* `America\/Goose_Bay` - America\/Goose_Bay\n\* `America\/Grand_Turk` - America\/Grand_Turk\n\* `America\/Grenada` - America\/Grenada\n\* `America\/Guadeloupe` - America\/Guadeloupe\n\* `America\/Guatemala` - America\/Guatemala\n\* `America\/Guayaquil` - America\/Guayaquil\n\* `America\/Guyana` - America\/Guyana\n\* `America\/Halifax` - America\/Halifax\n\* `America\/Havana` - America\/Havana\n\* `America\/Hermosillo` - America\/Hermosillo\n\* `America\/Indiana\/Indianapolis` - America\/Indiana\/Indianapolis\n\* `America\/Indiana\/Knox` - America\/Indiana\/Knox\n\* `America\/Indiana\/Marengo` - America\/Indiana\/Marengo\n\* `America\/Indiana\/Petersburg` - America\/Indiana\/Petersburg\n\* `America\/Indiana\/Tell_City` - America\/Indiana\/Tell_City\n\* `America\/Indiana\/Vevay` - America\/Indiana\/Vevay\n\* `America\/Indiana\/Vincennes` - America\/Indiana\/Vincennes\n\* `America\/Indiana\/Winamac` - America\/Indiana\/Winamac\n\* `America\/Indianapolis` - America\/Indianapolis\n\* `America\/Inuvik` - America\/Inuvik\n\* `America\/Iqaluit` - America\/Iqaluit\n\* `America\/Jamaica` - America\/Jamaica\n\* `America\/Jujuy` - America\/Jujuy\n\* `America\/Juneau` - America\/Juneau\n\* `America\/Kentucky\/Louisville` - America\/Kentucky\/Louisville\n\* `America\/Kentucky\/Monticello` - America\/Kentucky\/Monticello\n\* `America\/Knox_IN` - America\/Knox_IN\n\* `America\/Kralendijk` - America\/Kralendijk\n\* `America\/La_Paz` - America\/La_Paz\n\* `America\/Lima` - America\/Lima\n\* `America\/Los_Angeles` - America\/Los_Angeles\n\* `America\/Louisville` - America\/Louisville\n\* `America\/Lower_Princes` - America\/Lower_Princes\n\* `America\/Maceio` - America\/Maceio\n\* `America\/Managua` - America\/Managua\n\* `America\/Manaus` - America\/Manaus\n\* `America\/Marigot` - America\/Marigot\n\* `America\/Martinique` - America\/Martinique\n\* `America\/Matamoros` - America\/Matamoros\n\* `America\/Mazatlan` - America\/Mazatlan\n\* `America\/Mendoza` - America\/Mendoza\n\* `America\/Menominee` - America\/Menominee\n\* `America\/Merida` - America\/Merida\n\* `America\/Metlakatla` - America\/Metlakatla\n\* `America\/Mexico_City` - America\/Mexico_City\n\* `America\/Miquelon` - America\/Miquelon\n\* `America\/Moncton` - America\/Moncton\n\* `America\/Monterrey` - America\/Monterrey\n\* `America\/Montevideo` - America\/Montevideo\n\* `America\/Montreal` - America\/Montreal\n\* `America\/Montserrat` - America\/Montserrat\n\* `America\/Nassau` - America\/Nassau\n\* `America\/New_York` - America\/New_York\n\* `America\/Nipigon` - America\/Nipigon\n\* `America\/Nome` - America\/Nome\n\* `America\/Noronha` - America\/Noronha\n\* `America\/North_Dakota\/Beulah` - America\/North_Dakota\/Beulah\n\* `America\/North_Dakota\/Center` - America\/North_Dakota\/Center\n\* `America\/North_Dakota\/New_Salem` - America\/North_Dakota\/New_Salem\n\* `America\/Nuuk` - America\/Nuuk\n\* `America\/Ojinaga` - America\/Ojinaga\n\* `America\/Panama` - America\/Panama\n\* `America\/Pangnirtung` - America\/Pangnirtung\n\* `America\/Paramaribo` - America\/Paramaribo\n\* `America\/Phoenix` - America\/Phoenix\n\* `America\/Port-au-Prince` - America\/Port-au-Prince\n\* `America\/Port_of_Spain` - America\/Port_of_Spain\n\* `America\/Porto_Acre` - America\/Porto_Acre\n\* `America\/Porto_Velho` - America\/Porto_Velho\n\* `America\/Puerto_Rico` - America\/Puerto_Rico\n\* `America\/Punta_Arenas` - America\/Punta_Arenas\n\* `America\/Rainy_River` - America\/Rainy_River\n\* `America\/Rankin_Inlet` - America\/Rankin_Inlet\n\* `America\/Recife` - America\/Recife\n\* `America\/Regina` - America\/Regina\n\* `America\/Resolute` - America\/Resolute\n\* `America\/Rio_Branco` - America\/Rio_Branco\n\* `America\/Rosario` - America\/Rosario\n\* `America\/Santa_Isabel` - America\/Santa_Isabel\n\* `America\/Santarem` - America\/Santarem\n\* `America\/Santiago` - America\/Santiago\n\* `America\/Santo_Domingo` - America\/Santo_Domingo\n\* `America\/Sao_Paulo` - America\/Sao_Paulo\n\* `America\/Scoresbysund` - America\/Scoresbysund\n\* `America\/Shiprock` - America\/Shiprock\n\* `America\/Sitka` - America\/Sitka\n\* `America\/St_Barthelemy` - America\/St_Barthelemy\n\* `America\/St_Johns` - America\/St_Johns\n\* `America\/St_Kitts` - America\/St_Kitts\n\* `America\/St_Lucia` - America\/St_Lucia\n\* `America\/St_Thomas` - America\/St_Thomas\n\* `America\/St_Vincent` - America\/St_Vincent\n\* `America\/Swift_Current` - America\/Swift_Current\n\* `America\/Tegucigalpa` - America\/Tegucigalpa\n\* `America\/Thule` - America\/Thule\n\* `America\/Thunder_Bay` - America\/Thunder_Bay\n\* `America\/Tijuana` - America\/Tijuana\n\* `America\/Toronto` - America\/Toronto\n\* `America\/Tortola` - America\/Tortola\n\* `America\/Vancouver` - America\/Vancouver\n\* `America\/Virgin` - America\/Virgin\n\* `America\/Whitehorse` - America\/Whitehorse\n\* `America\/Winnipeg` - America\/Winnipeg\n\* `America\/Yakutat` - America\/Yakutat\n\* `America\/Yellowknife` - America\/Yellowknife\n\* `Antarctica\/Casey` - Antarctica\/Casey\n\* `Antarctica\/Davis` - Antarctica\/Davis\n\* `Antarctica\/DumontDUrville` - Antarctica\/DumontDUrville\n\* `Antarctica\/Macquarie` - Antarctica\/Macquarie\n\* `Antarctica\/Mawson` - Antarctica\/Mawson\n\* `Antarctica\/McMurdo` - Antarctica\/McMurdo\n\* `Antarctica\/Palmer` - Antarctica\/Palmer\n\* `Antarctica\/Rothera` - Antarctica\/Rothera\n\* `Antarctica\/South_Pole` - Antarctica\/South_Pole\n\* `Antarctica\/Syowa` - Antarctica\/Syowa\n\* `Antarctica\/Troll` - Antarctica\/Troll\n\* `Antarctica\/Vostok` - Antarctica\/Vostok\n\* `Arctic\/Longyearbyen` - Arctic\/Longyearbyen\n\* `Asia\/Aden` - Asia\/Aden\n\* `Asia\/Almaty` - Asia\/Almaty\n\* `Asia\/Amman` - Asia\/Amman\n\* `Asia\/Anadyr` - Asia\/Anadyr\n\* `Asia\/Aqtau` - Asia\/Aqtau\n\* `Asia\/Aqtobe` - Asia\/Aqtobe\n\* `Asia\/Ashgabat` - Asia\/Ashgabat\n\* `Asia\/Ashkhabad` - Asia\/Ashkhabad\n\* `Asia\/Atyrau` - Asia\/Atyrau\n\* `Asia\/Baghdad` - Asia\/Baghdad\n\* `Asia\/Bahrain` - Asia\/Bahrain\n\* `Asia\/Baku` - Asia\/Baku\n\* `Asia\/Bangkok` - Asia\/Bangkok\n\* `Asia\/Barnaul` - Asia\/Barnaul\n\* `Asia\/Beirut` - Asia\/Beirut\n\* `Asia\/Bishkek` - Asia\/Bishkek\n\* `Asia\/Brunei` - Asia\/Brunei\n\* `Asia\/Calcutta` - Asia\/Calcutta\n\* `Asia\/Chita` - Asia\/Chita\n\* `Asia\/Choibalsan` - Asia\/Choibalsan\n\* `Asia\/Chongqing` - Asia\/Chongqing\n\* `Asia\/Chungking` - Asia\/Chungking\n\* `Asia\/Colombo` - Asia\/Colombo\n\* `Asia\/Dacca` - Asia\/Dacca\n\* `Asia\/Damascus` - Asia\/Damascus\n\* `Asia\/Dhaka` - Asia\/Dhaka\n\* `Asia\/Dili` - Asia\/Dili\n\* `Asia\/Dubai` - Asia\/Dubai\n\* `Asia\/Dushanbe` - Asia\/Dushanbe\n\* `Asia\/Famagusta` - Asia\/Famagusta\n\* `Asia\/Gaza` - Asia\/Gaza\n\* `Asia\/Harbin` - Asia\/Harbin\n\* `Asia\/Hebron` - Asia\/Hebron\n\* `Asia\/Ho_Chi_Minh` - Asia\/Ho_Chi_Minh\n\* `Asia\/Hong_Kong` - Asia\/Hong_Kong\n\* `Asia\/Hovd` - Asia\/Hovd\n\* `Asia\/Irkutsk` - Asia\/Irkutsk\n\* `Asia\/Istanbul` - Asia\/Istanbul\n\* `Asia\/Jakarta` - Asia\/Jakarta\n\* `Asia\/Jayapura` - Asia\/Jayapura\n\* `Asia\/Jerusalem` - Asia\/Jerusalem\n\* `Asia\/Kabul` - Asia\/Kabul\n\* `Asia\/Kamchatka` - Asia\/Kamchatka\n\* `Asia\/Karachi` - Asia\/Karachi\n\* `Asia\/Kashgar` - Asia\/Kashgar\n\* `Asia\/Kathmandu` - Asia\/Kathmandu\n\* `Asia\/Katmandu` - Asia\/Katmandu\n\* `Asia\/Khandyga` - Asia\/Khandyga\n\* `Asia\/Kolkata` - Asia\/Kolkata\n\* `Asia\/Krasnoyarsk` - Asia\/Krasnoyarsk\n\* `Asia\/Kuala_Lumpur` - Asia\/Kuala_Lumpur\n\* `Asia\/Kuching` - Asia\/Kuching\n\* `Asia\/Kuwait` - Asia\/Kuwait\n\* `Asia\/Macao` - Asia\/Macao\n\* `Asia\/Macau` - Asia\/Macau\n\* `Asia\/Magadan` - Asia\/Magadan\n\* `Asia\/Makassar` - Asia\/Makassar\n\* `Asia\/Manila` - Asia\/Manila\n\* `Asia\/Muscat` - Asia\/Muscat\n\* `Asia\/Nicosia` - Asia\/Nicosia\n\* `Asia\/Novokuznetsk` - Asia\/Novokuznetsk\n\* `Asia\/Novosibirsk` - Asia\/Novosibirsk\n\* `Asia\/Omsk` - Asia\/Omsk\n\* `Asia\/Oral` - Asia\/Oral\n\* `Asia\/Phnom_Penh` - Asia\/Phnom_Penh\n\* `Asia\/Pontianak` - Asia\/Pontianak\n\* `Asia\/Pyongyang` - Asia\/Pyongyang\n\* `Asia\/Qatar` - Asia\/Qatar\n\* `Asia\/Qostanay` - Asia\/Qostanay\n\* `Asia\/Qyzylorda` - Asia\/Qyzylorda\n\* `Asia\/Rangoon` - Asia\/Rangoon\n\* `Asia\/Riyadh` - Asia\/Riyadh\n\* `Asia\/Saigon` - Asia\/Saigon\n\* `Asia\/Sakhalin` - Asia\/Sakhalin\n\* `Asia\/Samarkand` - Asia\/Samarkand\n\* `Asia\/Seoul` - Asia\/Seoul\n\* `Asia\/Shanghai` - Asia\/Shanghai\n\* `Asia\/Singapore` - Asia\/Singapore\n\* `Asia\/Srednekolymsk` - Asia\/Srednekolymsk\n\* `Asia\/Taipei` - Asia\/Taipei\n\* `Asia\/Tashkent` - Asia\/Tashkent\n\* `Asia\/Tbilisi` - Asia\/Tbilisi\n\* `Asia\/Tehran` - Asia\/Tehran\n\* `Asia\/Tel_Aviv` - Asia\/Tel_Aviv\n\* `Asia\/Thimbu` - Asia\/Thimbu\n\* `Asia\/Thimphu` - Asia\/Thimphu\n\* `Asia\/Tokyo` - Asia\/Tokyo\n\* `Asia\/Tomsk` - Asia\/Tomsk\n\* `Asia\/Ujung_Pandang` - Asia\/Ujung_Pandang\n\* `Asia\/Ulaanbaatar` - Asia\/Ulaanbaatar\n\* `Asia\/Ulan_Bator` - Asia\/Ulan_Bator\n\* `Asia\/Urumqi` - Asia\/Urumqi\n\* `Asia\/Ust-Nera` - Asia\/Ust-Nera\n\* `Asia\/Vientiane` - Asia\/Vientiane\n\* `Asia\/Vladivostok` - Asia\/Vladivostok\n\* `Asia\/Yakutsk` - Asia\/Yakutsk\n\* `Asia\/Yangon` - Asia\/Yangon\n\* `Asia\/Yekaterinburg` - Asia\/Yekaterinburg\n\* `Asia\/Yerevan` - Asia\/Yerevan\n\* `Atlantic\/Azores` - Atlantic\/Azores\n\* `Atlantic\/Bermuda` - Atlantic\/Bermuda\n\* `Atlantic\/Canary` - Atlantic\/Canary\n\* `Atlantic\/Cape_Verde` - Atlantic\/Cape_Verde\n\* `Atlantic\/Faeroe` - Atlantic\/Faeroe\n\* `Atlantic\/Faroe` - Atlantic\/Faroe\n\* `Atlantic\/Jan_Mayen` - Atlantic\/Jan_Mayen\n\* `Atlantic\/Madeira` - Atlantic\/Madeira\n\* `Atlantic\/Reykjavik` - Atlantic\/Reykjavik\n\* `Atlantic\/South_Georgia` - Atlantic\/South_Georgia\n\* `Atlantic\/St_Helena` - Atlantic\/St_Helena\n\* `Atlantic\/Stanley` - Atlantic\/Stanley\n\* `Australia\/ACT` - Australia\/ACT\n\* `Australia\/Adelaide` - Australia\/Adelaide\n\* `Australia\/Brisbane` - Australia\/Brisbane\n\* `Australia\/Broken_Hill` - Australia\/Broken_Hill\n\* `Australia\/Canberra` - Australia\/Canberra\n\* `Australia\/Currie` - Australia\/Currie\n\* `Australia\/Darwin` - Australia\/Darwin\n\* `Australia\/Eucla` - Australia\/Eucla\n\* `Australia\/Hobart` - Australia\/Hobart\n\* `Australia\/LHI` - Australia\/LHI\n\* `Australia\/Lindeman` - Australia\/Lindeman\n\* `Australia\/Lord_Howe` - Australia\/Lord_Howe\n\* `Australia\/Melbourne` - Australia\/Melbourne\n\* `Australia\/NSW` - Australia\/NSW\n\* `Australia\/North` - Australia\/North\n\* `Australia\/Perth` - Australia\/Perth\n\* `Australia\/Queensland` - Australia\/Queensland\n\* `Australia\/South` - Australia\/South\n\* `Australia\/Sydney` - Australia\/Sydney\n\* `Australia\/Tasmania` - Australia\/Tasmania\n\* `Australia\/Victoria` - Australia\/Victoria\n\* `Australia\/West` - Australia\/West\n\* `Australia\/Yancowinna` - Australia\/Yancowinna\n\* `Brazil\/Acre` - Brazil\/Acre\n\* `Brazil\/DeNoronha` - Brazil\/DeNoronha\n\* `Brazil\/East` - Brazil\/East\n\* `Brazil\/West` - Brazil\/West\n\* `CET` - CET\n\* `CST6CDT` - CST6CDT\n\* `Canada\/Atlantic` - Canada\/Atlantic\n\* `Canada\/Central` - Canada\/Central\n\* `Canada\/Eastern` - Canada\/Eastern\n\* `Canada\/Mountain` - Canada\/Mountain\n\* `Canada\/Newfoundland` - Canada\/Newfoundland\n\* `Canada\/Pacific` - Canada\/Pacific\n\* `Canada\/Saskatchewan` - Canada\/Saskatchewan\n\* `Canada\/Yukon` - Canada\/Yukon\n\* `Chile\/Continental` - Chile\/Continental\n\* `Chile\/EasterIsland` - Chile\/EasterIsland\n\* `Cuba` - Cuba\n\* `EET` - EET\n\* `EST` - EST\n\* `EST5EDT` - EST5EDT\n\* `Egypt` - Egypt\n\* `Eire` - Eire\n\* `Etc\/GMT` - Etc\/GMT\n\* `Etc\/GMT+0` - Etc\/GMT+0\n\* `Etc\/GMT+1` - Etc\/GMT+1\n\* `Etc\/GMT+10` - Etc\/GMT+10\n\* `Etc\/GMT+11` - Etc\/GMT+11\n\* `Etc\/GMT+12` - Etc\/GMT+12\n\* `Etc\/GMT+2` - Etc\/GMT+2\n\* `Etc\/GMT+3` - Etc\/GMT+3\n\* `Etc\/GMT+4` - Etc\/GMT+4\n\* `Etc\/GMT+5` - Etc\/GMT+5\n\* `Etc\/GMT+6` - Etc\/GMT+6\n\* `Etc\/GMT+7` - Etc\/GMT+7\n\* `Etc\/GMT+8` - Etc\/GMT+8\n\* `Etc\/GMT+9` - Etc\/GMT+9\n\* `Etc\/GMT-0` - Etc\/GMT-0\n\* `Etc\/GMT-1` - Etc\/GMT-1\n\* `Etc\/GMT-10` - Etc\/GMT-10\n\* `Etc\/GMT-11` - Etc\/GMT-11\n\* `Etc\/GMT-12` - Etc\/GMT-12\n\* `Etc\/GMT-13` - Etc\/GMT-13\n\* `Etc\/GMT-14` - Etc\/GMT-14\n\* `Etc\/GMT-2` - Etc\/GMT-2\n\* `Etc\/GMT-3` - Etc\/GMT-3\n\* `Etc\/GMT-4` - Etc\/GMT-4\n\* `Etc\/GMT-5` - Etc\/GMT-5\n\* `Etc\/GMT-6` - Etc\/GMT-6\n\* `Etc\/GMT-7` - Etc\/GMT-7\n\* `Etc\/GMT-8` - Etc\/GMT-8\n\* `Etc\/GMT-9` - Etc\/GMT-9\n\* `Etc\/GMT0` - Etc\/GMT0\n\* `Etc\/Greenwich` - Etc\/Greenwich\n\* `Etc\/UCT` - Etc\/UCT\n\* `Etc\/UTC` - Etc\/UTC\n\* `Etc\/Universal` - Etc\/Universal\n\* `Etc\/Zulu` - Etc\/Zulu\n\* `Europe\/Amsterdam` - Europe\/Amsterdam\n\* `Europe\/Andorra` - Europe\/Andorra\n\* `Europe\/Astrakhan` - Europe\/Astrakhan\n\* `Europe\/Athens` - Europe\/Athens\n\* `Europe\/Belfast` - Europe\/Belfast\n\* `Europe\/Belgrade` - Europe\/Belgrade\n\* `Europe\/Berlin` - Europe\/Berlin\n\* `Europe\/Bratislava` - Europe\/Bratislava\n\* `Europe\/Brussels` - Europe\/Brussels\n\* `Europe\/Bucharest` - Europe\/Bucharest\n\* `Europe\/Budapest` - Europe\/Budapest\n\* `Europe\/Busingen` - Europe\/Busingen\n\* `Europe\/Chisinau` - Europe\/Chisinau\n\* `Europe\/Copenhagen` - Europe\/Copenhagen\n\* `Europe\/Dublin` - Europe\/Dublin\n\* `Europe\/Gibraltar` - Europe\/Gibraltar\n\* `Europe\/Guernsey` - Europe\/Guernsey\n\* `Europe\/Helsinki` - Europe\/Helsinki\n\* `Europe\/Isle_of_Man` - Europe\/Isle_of_Man\n\* `Europe\/Istanbul` - Europe\/Istanbul\n\* `Europe\/Jersey` - Europe\/Jersey\n\* `Europe\/Kaliningrad` - Europe\/Kaliningrad\n\* `Europe\/Kiev` - Europe\/Kiev\n\* `Europe\/Kirov` - Europe\/Kirov\n\* `Europe\/Kyiv` - Europe\/Kyiv\n\* `Europe\/Lisbon` - Europe\/Lisbon\n\* `Europe\/Ljubljana` - Europe\/Ljubljana\n\* `Europe\/London` - Europe\/London\n\* `Europe\/Luxembourg` - Europe\/Luxembourg\n\* `Europe\/Madrid` - Europe\/Madrid\n\* `Europe\/Malta` - Europe\/Malta\n\* `Europe\/Mariehamn` - Europe\/Mariehamn\n\* `Europe\/Minsk` - Europe\/Minsk\n\* `Europe\/Monaco` - Europe\/Monaco\n\* `Europe\/Moscow` - Europe\/Moscow\n\* `Europe\/Nicosia` - Europe\/Nicosia\n\* `Europe\/Oslo` - Europe\/Oslo\n\* `Europe\/Paris` - Europe\/Paris\n\* `Europe\/Podgorica` - Europe\/Podgorica\n\* `Europe\/Prague` - Europe\/Prague\n\* `Europe\/Riga` - Europe\/Riga\n\* `Europe\/Rome` - Europe\/Rome\n\* `Europe\/Samara` - Europe\/Samara\n\* `Europe\/San_Marino` - Europe\/San_Marino\n\* `Europe\/Sarajevo` - Europe\/Sarajevo\n\* `Europe\/Saratov` - Europe\/Saratov\n\* `Europe\/Simferopol` - Europe\/Simferopol\n\* `Europe\/Skopje` - Europe\/Skopje\n\* `Europe\/Sofia` - Europe\/Sofia\n\* `Europe\/Stockholm` - Europe\/Stockholm\n\* `Europe\/Tallinn` - Europe\/Tallinn\n\* `Europe\/Tirane` - Europe\/Tirane\n\* `Europe\/Tiraspol` - Europe\/Tiraspol\n\* `Europe\/Ulyanovsk` - Europe\/Ulyanovsk\n\* `Europe\/Uzhgorod` - Europe\/Uzhgorod\n\* `Europe\/Vaduz` - Europe\/Vaduz\n\* `Europe\/Vatican` - Europe\/Vatican\n\* `Europe\/Vienna` - Europe\/Vienna\n\* `Europe\/Vilnius` - Europe\/Vilnius\n\* `Europe\/Volgograd` - Europe\/Volgograd\n\* `Europe\/Warsaw` - Europe\/Warsaw\n\* `Europe\/Zagreb` - Europe\/Zagreb\n\* `Europe\/Zaporozhye` - Europe\/Zaporozhye\n\* `Europe\/Zurich` - Europe\/Zurich\n\* `GB` - GB\n\* `GB-Eire` - GB-Eire\n\* `GMT` - GMT\n\* `GMT+0` - GMT+0\n\* `GMT-0` - GMT-0\n\* `GMT0` - GMT0\n\* `Greenwich` - Greenwich\n\* `HST` - HST\n\* `Hongkong` - Hongkong\n\* `Iceland` - Iceland\n\* `Indian\/Antananarivo` - Indian\/Antananarivo\n\* `Indian\/Chagos` - Indian\/Chagos\n\* `Indian\/Christmas` - Indian\/Christmas\n\* `Indian\/Cocos` - Indian\/Cocos\n\* `Indian\/Comoro` - Indian\/Comoro\n\* `Indian\/Kerguelen` - Indian\/Kerguelen\n\* `Indian\/Mahe` - Indian\/Mahe\n\* `Indian\/Maldives` - Indian\/Maldives\n\* `Indian\/Mauritius` - Indian\/Mauritius\n\* `Indian\/Mayotte` - Indian\/Mayotte\n\* `Indian\/Reunion` - Indian\/Reunion\n\* `Iran` - Iran\n\* `Israel` - Israel\n\* `Jamaica` - Jamaica\n\* `Japan` - Japan\n\* `Kwajalein` - Kwajalein\n\* `Libya` - Libya\n\* `MET` - MET\n\* `MST` - MST\n\* `MST7MDT` - MST7MDT\n\* `Mexico\/BajaNorte` - Mexico\/BajaNorte\n\* `Mexico\/BajaSur` - Mexico\/BajaSur\n\* `Mexico\/General` - Mexico\/General\n\* `NZ` - NZ\n\* `NZ-CHAT` - NZ-CHAT\n\* `Navajo` - Navajo\n\* `PRC` - PRC\n\* `PST8PDT` - PST8PDT\n\* `Pacific\/Apia` - Pacific\/Apia\n\* `Pacific\/Auckland` - Pacific\/Auckland\n\* `Pacific\/Bougainville` - Pacific\/Bougainville\n\* `Pacific\/Chatham` - Pacific\/Chatham\n\* `Pacific\/Chuuk` - Pacific\/Chuuk\n\* `Pacific\/Easter` - Pacific\/Easter\n\* `Pacific\/Efate` - Pacific\/Efate\n\* `Pacific\/Enderbury` - Pacific\/Enderbury\n\* `Pacific\/Fakaofo` - Pacific\/Fakaofo\n\* `Pacific\/Fiji` - Pacific\/Fiji\n\* `Pacific\/Funafuti` - Pacific\/Funafuti\n\* `Pacific\/Galapagos` - Pacific\/Galapagos\n\* `Pacific\/Gambier` - Pacific\/Gambier\n\* `Pacific\/Guadalcanal` - Pacific\/Guadalcanal\n\* `Pacific\/Guam` - Pacific\/Guam\n\* `Pacific\/Honolulu` - Pacific\/Honolulu\n\* `Pacific\/Johnston` - Pacific\/Johnston\n\* `Pacific\/Kanton` - Pacific\/Kanton\n\* `Pacific\/Kiritimati` - Pacific\/Kiritimati\n\* `Pacific\/Kosrae` - Pacific\/Kosrae\n\* `Pacific\/Kwajalein` - Pacific\/Kwajalein\n\* `Pacific\/Majuro` - Pacific\/Majuro\n\* `Pacific\/Marquesas` - Pacific\/Marquesas\n\* `Pacific\/Midway` - Pacific\/Midway\n\* `Pacific\/Nauru` - Pacific\/Nauru\n\* `Pacific\/Niue` - Pacific\/Niue\n\* `Pacific\/Norfolk` - Pacific\/Norfolk\n\* `Pacific\/Noumea` - Pacific\/Noumea\n\* `Pacific\/Pago_Pago` - Pacific\/Pago_Pago\n\* `Pacific\/Palau` - Pacific\/Palau\n\* `Pacific\/Pitcairn` - Pacific\/Pitcairn\n\* `Pacific\/Pohnpei` - Pacific\/Pohnpei\n\* `Pacific\/Ponape` - Pacific\/Ponape\n\* `Pacific\/Port_Moresby` - Pacific\/Port_Moresby\n\* `Pacific\/Rarotonga` - Pacific\/Rarotonga\n\* `Pacific\/Saipan` - Pacific\/Saipan\n\* `Pacific\/Samoa` - Pacific\/Samoa\n\* `Pacific\/Tahiti` - Pacific\/Tahiti\n\* `Pacific\/Tarawa` - Pacific\/Tarawa\n\* `Pacific\/Tongatapu` - Pacific\/Tongatapu\n\* `Pacific\/Truk` - Pacific\/Truk\n\* `Pacific\/Wake` - Pacific\/Wake\n\* `Pacific\/Wallis` - Pacific\/Wallis\n\* `Pacific\/Yap` - Pacific\/Yap\n\* `Poland` - Poland\n\* `Portugal` - Portugal\n\* `ROC` - ROC\n\* `ROK` - ROK\n\* `Singapore` - Singapore\n\* `Turkey` - Turkey\n\* `UCT` - UCT\n\* `US\/Alaska` - US\/Alaska\n\* `US\/Aleutian` - US\/Aleutian\n\* `US\/Arizona` - US\/Arizona\n\* `US\/Central` - US\/Central\n\* `US\/East-Indiana` - US\/East-Indiana\n\* `US\/Eastern` - US\/Eastern\n\* `US\/Hawaii` - US\/Hawaii\n\* `US\/Indiana-Starke` - US\/Indiana-Starke\n\* `US\/Michigan` - US\/Michigan\n\* `US\/Mountain` - US\/Mountain\n\* `US\/Pacific` - US\/Pacific\n\* `US\/Samoa` - US\/Samoa\n\* `UTC` - UTC\n\* `Universal` - Universal\n\* `W-SU` - W-SU\n\* `WET` - WET\n\* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsAddProductIntentPartialUpdateBodyPersonDisplayNamePropertiesItemMax)
            )
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat(
                'decimal',
                organizationsProjectsAddProductIntentPartialUpdateBodySessionRecordingSampleRateRegExp
            )
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(organizationsProjectsAddProductIntentPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(organizationsProjectsAddProductIntentPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(organizationsProjectsAddProductIntentPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('\* `0` - Sunday\n\* `1` - Monday'),
                zod.null(),
            ])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n\* `0` - Sunday\n\* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsAddProductIntentPartialUpdateBodyRecordingDomainsItemMax)
                    .nullable()
            )
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations \/ live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(
                        organizationsProjectsAddProductIntentPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax
                    )
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsAddProductIntentPartialUpdateBodyDefaultDataThemeMin)
            .max(organizationsProjectsAddProductIntentPartialUpdateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Projects for the current organization.
 */
export const organizationsProjectsChangeOrganizationCreateBodyNameMax = 200

export const organizationsProjectsChangeOrganizationCreateBodyProductDescriptionMax = 1000

export const organizationsProjectsChangeOrganizationCreateBodyAppUrlsItemMax = 200

export const organizationsProjectsChangeOrganizationCreateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsChangeOrganizationCreateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const organizationsProjectsChangeOrganizationCreateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsChangeOrganizationCreateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsChangeOrganizationCreateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsChangeOrganizationCreateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsChangeOrganizationCreateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsChangeOrganizationCreateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsChangeOrganizationCreateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsChangeOrganizationCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsChangeOrganizationCreateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsChangeOrganizationCreateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(zod.string().max(organizationsProjectsChangeOrganizationCreateBodyAppUrlsItemMax).nullable())
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal\/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal\/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America\/Los_Angeles`).\n\n\* `Africa\/Abidjan` - Africa\/Abidjan\n\* `Africa\/Accra` - Africa\/Accra\n\* `Africa\/Addis_Ababa` - Africa\/Addis_Ababa\n\* `Africa\/Algiers` - Africa\/Algiers\n\* `Africa\/Asmara` - Africa\/Asmara\n\* `Africa\/Asmera` - Africa\/Asmera\n\* `Africa\/Bamako` - Africa\/Bamako\n\* `Africa\/Bangui` - Africa\/Bangui\n\* `Africa\/Banjul` - Africa\/Banjul\n\* `Africa\/Bissau` - Africa\/Bissau\n\* `Africa\/Blantyre` - Africa\/Blantyre\n\* `Africa\/Brazzaville` - Africa\/Brazzaville\n\* `Africa\/Bujumbura` - Africa\/Bujumbura\n\* `Africa\/Cairo` - Africa\/Cairo\n\* `Africa\/Casablanca` - Africa\/Casablanca\n\* `Africa\/Ceuta` - Africa\/Ceuta\n\* `Africa\/Conakry` - Africa\/Conakry\n\* `Africa\/Dakar` - Africa\/Dakar\n\* `Africa\/Dar_es_Salaam` - Africa\/Dar_es_Salaam\n\* `Africa\/Djibouti` - Africa\/Djibouti\n\* `Africa\/Douala` - Africa\/Douala\n\* `Africa\/El_Aaiun` - Africa\/El_Aaiun\n\* `Africa\/Freetown` - Africa\/Freetown\n\* `Africa\/Gaborone` - Africa\/Gaborone\n\* `Africa\/Harare` - Africa\/Harare\n\* `Africa\/Johannesburg` - Africa\/Johannesburg\n\* `Africa\/Juba` - Africa\/Juba\n\* `Africa\/Kampala` - Africa\/Kampala\n\* `Africa\/Khartoum` - Africa\/Khartoum\n\* `Africa\/Kigali` - Africa\/Kigali\n\* `Africa\/Kinshasa` - Africa\/Kinshasa\n\* `Africa\/Lagos` - Africa\/Lagos\n\* `Africa\/Libreville` - Africa\/Libreville\n\* `Africa\/Lome` - Africa\/Lome\n\* `Africa\/Luanda` - Africa\/Luanda\n\* `Africa\/Lubumbashi` - Africa\/Lubumbashi\n\* `Africa\/Lusaka` - Africa\/Lusaka\n\* `Africa\/Malabo` - Africa\/Malabo\n\* `Africa\/Maputo` - Africa\/Maputo\n\* `Africa\/Maseru` - Africa\/Maseru\n\* `Africa\/Mbabane` - Africa\/Mbabane\n\* `Africa\/Mogadishu` - Africa\/Mogadishu\n\* `Africa\/Monrovia` - Africa\/Monrovia\n\* `Africa\/Nairobi` - Africa\/Nairobi\n\* `Africa\/Ndjamena` - Africa\/Ndjamena\n\* `Africa\/Niamey` - Africa\/Niamey\n\* `Africa\/Nouakchott` - Africa\/Nouakchott\n\* `Africa\/Ouagadougou` - Africa\/Ouagadougou\n\* `Africa\/Porto-Novo` - Africa\/Porto-Novo\n\* `Africa\/Sao_Tome` - Africa\/Sao_Tome\n\* `Africa\/Timbuktu` - Africa\/Timbuktu\n\* `Africa\/Tripoli` - Africa\/Tripoli\n\* `Africa\/Tunis` - Africa\/Tunis\n\* `Africa\/Windhoek` - Africa\/Windhoek\n\* `America\/Adak` - America\/Adak\n\* `America\/Anchorage` - America\/Anchorage\n\* `America\/Anguilla` - America\/Anguilla\n\* `America\/Antigua` - America\/Antigua\n\* `America\/Araguaina` - America\/Araguaina\n\* `America\/Argentina\/Buenos_Aires` - America\/Argentina\/Buenos_Aires\n\* `America\/Argentina\/Catamarca` - America\/Argentina\/Catamarca\n\* `America\/Argentina\/ComodRivadavia` - America\/Argentina\/ComodRivadavia\n\* `America\/Argentina\/Cordoba` - America\/Argentina\/Cordoba\n\* `America\/Argentina\/Jujuy` - America\/Argentina\/Jujuy\n\* `America\/Argentina\/La_Rioja` - America\/Argentina\/La_Rioja\n\* `America\/Argentina\/Mendoza` - America\/Argentina\/Mendoza\n\* `America\/Argentina\/Rio_Gallegos` - America\/Argentina\/Rio_Gallegos\n\* `America\/Argentina\/Salta` - America\/Argentina\/Salta\n\* `America\/Argentina\/San_Juan` - America\/Argentina\/San_Juan\n\* `America\/Argentina\/San_Luis` - America\/Argentina\/San_Luis\n\* `America\/Argentina\/Tucuman` - America\/Argentina\/Tucuman\n\* `America\/Argentina\/Ushuaia` - America\/Argentina\/Ushuaia\n\* `America\/Aruba` - America\/Aruba\n\* `America\/Asuncion` - America\/Asuncion\n\* `America\/Atikokan` - America\/Atikokan\n\* `America\/Atka` - America\/Atka\n\* `America\/Bahia` - America\/Bahia\n\* `America\/Bahia_Banderas` - America\/Bahia_Banderas\n\* `America\/Barbados` - America\/Barbados\n\* `America\/Belem` - America\/Belem\n\* `America\/Belize` - America\/Belize\n\* `America\/Blanc-Sablon` - America\/Blanc-Sablon\n\* `America\/Boa_Vista` - America\/Boa_Vista\n\* `America\/Bogota` - America\/Bogota\n\* `America\/Boise` - America\/Boise\n\* `America\/Buenos_Aires` - America\/Buenos_Aires\n\* `America\/Cambridge_Bay` - America\/Cambridge_Bay\n\* `America\/Campo_Grande` - America\/Campo_Grande\n\* `America\/Cancun` - America\/Cancun\n\* `America\/Caracas` - America\/Caracas\n\* `America\/Catamarca` - America\/Catamarca\n\* `America\/Cayenne` - America\/Cayenne\n\* `America\/Cayman` - America\/Cayman\n\* `America\/Chicago` - America\/Chicago\n\* `America\/Chihuahua` - America\/Chihuahua\n\* `America\/Ciudad_Juarez` - America\/Ciudad_Juarez\n\* `America\/Coral_Harbour` - America\/Coral_Harbour\n\* `America\/Cordoba` - America\/Cordoba\n\* `America\/Costa_Rica` - America\/Costa_Rica\n\* `America\/Creston` - America\/Creston\n\* `America\/Cuiaba` - America\/Cuiaba\n\* `America\/Curacao` - America\/Curacao\n\* `America\/Danmarkshavn` - America\/Danmarkshavn\n\* `America\/Dawson` - America\/Dawson\n\* `America\/Dawson_Creek` - America\/Dawson_Creek\n\* `America\/Denver` - America\/Denver\n\* `America\/Detroit` - America\/Detroit\n\* `America\/Dominica` - America\/Dominica\n\* `America\/Edmonton` - America\/Edmonton\n\* `America\/Eirunepe` - America\/Eirunepe\n\* `America\/El_Salvador` - America\/El_Salvador\n\* `America\/Ensenada` - America\/Ensenada\n\* `America\/Fort_Nelson` - America\/Fort_Nelson\n\* `America\/Fort_Wayne` - America\/Fort_Wayne\n\* `America\/Fortaleza` - America\/Fortaleza\n\* `America\/Glace_Bay` - America\/Glace_Bay\n\* `America\/Godthab` - America\/Godthab\n\* `America\/Goose_Bay` - America\/Goose_Bay\n\* `America\/Grand_Turk` - America\/Grand_Turk\n\* `America\/Grenada` - America\/Grenada\n\* `America\/Guadeloupe` - America\/Guadeloupe\n\* `America\/Guatemala` - America\/Guatemala\n\* `America\/Guayaquil` - America\/Guayaquil\n\* `America\/Guyana` - America\/Guyana\n\* `America\/Halifax` - America\/Halifax\n\* `America\/Havana` - America\/Havana\n\* `America\/Hermosillo` - America\/Hermosillo\n\* `America\/Indiana\/Indianapolis` - America\/Indiana\/Indianapolis\n\* `America\/Indiana\/Knox` - America\/Indiana\/Knox\n\* `America\/Indiana\/Marengo` - America\/Indiana\/Marengo\n\* `America\/Indiana\/Petersburg` - America\/Indiana\/Petersburg\n\* `America\/Indiana\/Tell_City` - America\/Indiana\/Tell_City\n\* `America\/Indiana\/Vevay` - America\/Indiana\/Vevay\n\* `America\/Indiana\/Vincennes` - America\/Indiana\/Vincennes\n\* `America\/Indiana\/Winamac` - America\/Indiana\/Winamac\n\* `America\/Indianapolis` - America\/Indianapolis\n\* `America\/Inuvik` - America\/Inuvik\n\* `America\/Iqaluit` - America\/Iqaluit\n\* `America\/Jamaica` - America\/Jamaica\n\* `America\/Jujuy` - America\/Jujuy\n\* `America\/Juneau` - America\/Juneau\n\* `America\/Kentucky\/Louisville` - America\/Kentucky\/Louisville\n\* `America\/Kentucky\/Monticello` - America\/Kentucky\/Monticello\n\* `America\/Knox_IN` - America\/Knox_IN\n\* `America\/Kralendijk` - America\/Kralendijk\n\* `America\/La_Paz` - America\/La_Paz\n\* `America\/Lima` - America\/Lima\n\* `America\/Los_Angeles` - America\/Los_Angeles\n\* `America\/Louisville` - America\/Louisville\n\* `America\/Lower_Princes` - America\/Lower_Princes\n\* `America\/Maceio` - America\/Maceio\n\* `America\/Managua` - America\/Managua\n\* `America\/Manaus` - America\/Manaus\n\* `America\/Marigot` - America\/Marigot\n\* `America\/Martinique` - America\/Martinique\n\* `America\/Matamoros` - America\/Matamoros\n\* `America\/Mazatlan` - America\/Mazatlan\n\* `America\/Mendoza` - America\/Mendoza\n\* `America\/Menominee` - America\/Menominee\n\* `America\/Merida` - America\/Merida\n\* `America\/Metlakatla` - America\/Metlakatla\n\* `America\/Mexico_City` - America\/Mexico_City\n\* `America\/Miquelon` - America\/Miquelon\n\* `America\/Moncton` - America\/Moncton\n\* `America\/Monterrey` - America\/Monterrey\n\* `America\/Montevideo` - America\/Montevideo\n\* `America\/Montreal` - America\/Montreal\n\* `America\/Montserrat` - America\/Montserrat\n\* `America\/Nassau` - America\/Nassau\n\* `America\/New_York` - America\/New_York\n\* `America\/Nipigon` - America\/Nipigon\n\* `America\/Nome` - America\/Nome\n\* `America\/Noronha` - America\/Noronha\n\* `America\/North_Dakota\/Beulah` - America\/North_Dakota\/Beulah\n\* `America\/North_Dakota\/Center` - America\/North_Dakota\/Center\n\* `America\/North_Dakota\/New_Salem` - America\/North_Dakota\/New_Salem\n\* `America\/Nuuk` - America\/Nuuk\n\* `America\/Ojinaga` - America\/Ojinaga\n\* `America\/Panama` - America\/Panama\n\* `America\/Pangnirtung` - America\/Pangnirtung\n\* `America\/Paramaribo` - America\/Paramaribo\n\* `America\/Phoenix` - America\/Phoenix\n\* `America\/Port-au-Prince` - America\/Port-au-Prince\n\* `America\/Port_of_Spain` - America\/Port_of_Spain\n\* `America\/Porto_Acre` - America\/Porto_Acre\n\* `America\/Porto_Velho` - America\/Porto_Velho\n\* `America\/Puerto_Rico` - America\/Puerto_Rico\n\* `America\/Punta_Arenas` - America\/Punta_Arenas\n\* `America\/Rainy_River` - America\/Rainy_River\n\* `America\/Rankin_Inlet` - America\/Rankin_Inlet\n\* `America\/Recife` - America\/Recife\n\* `America\/Regina` - America\/Regina\n\* `America\/Resolute` - America\/Resolute\n\* `America\/Rio_Branco` - America\/Rio_Branco\n\* `America\/Rosario` - America\/Rosario\n\* `America\/Santa_Isabel` - America\/Santa_Isabel\n\* `America\/Santarem` - America\/Santarem\n\* `America\/Santiago` - America\/Santiago\n\* `America\/Santo_Domingo` - America\/Santo_Domingo\n\* `America\/Sao_Paulo` - America\/Sao_Paulo\n\* `America\/Scoresbysund` - America\/Scoresbysund\n\* `America\/Shiprock` - America\/Shiprock\n\* `America\/Sitka` - America\/Sitka\n\* `America\/St_Barthelemy` - America\/St_Barthelemy\n\* `America\/St_Johns` - America\/St_Johns\n\* `America\/St_Kitts` - America\/St_Kitts\n\* `America\/St_Lucia` - America\/St_Lucia\n\* `America\/St_Thomas` - America\/St_Thomas\n\* `America\/St_Vincent` - America\/St_Vincent\n\* `America\/Swift_Current` - America\/Swift_Current\n\* `America\/Tegucigalpa` - America\/Tegucigalpa\n\* `America\/Thule` - America\/Thule\n\* `America\/Thunder_Bay` - America\/Thunder_Bay\n\* `America\/Tijuana` - America\/Tijuana\n\* `America\/Toronto` - America\/Toronto\n\* `America\/Tortola` - America\/Tortola\n\* `America\/Vancouver` - America\/Vancouver\n\* `America\/Virgin` - America\/Virgin\n\* `America\/Whitehorse` - America\/Whitehorse\n\* `America\/Winnipeg` - America\/Winnipeg\n\* `America\/Yakutat` - America\/Yakutat\n\* `America\/Yellowknife` - America\/Yellowknife\n\* `Antarctica\/Casey` - Antarctica\/Casey\n\* `Antarctica\/Davis` - Antarctica\/Davis\n\* `Antarctica\/DumontDUrville` - Antarctica\/DumontDUrville\n\* `Antarctica\/Macquarie` - Antarctica\/Macquarie\n\* `Antarctica\/Mawson` - Antarctica\/Mawson\n\* `Antarctica\/McMurdo` - Antarctica\/McMurdo\n\* `Antarctica\/Palmer` - Antarctica\/Palmer\n\* `Antarctica\/Rothera` - Antarctica\/Rothera\n\* `Antarctica\/South_Pole` - Antarctica\/South_Pole\n\* `Antarctica\/Syowa` - Antarctica\/Syowa\n\* `Antarctica\/Troll` - Antarctica\/Troll\n\* `Antarctica\/Vostok` - Antarctica\/Vostok\n\* `Arctic\/Longyearbyen` - Arctic\/Longyearbyen\n\* `Asia\/Aden` - Asia\/Aden\n\* `Asia\/Almaty` - Asia\/Almaty\n\* `Asia\/Amman` - Asia\/Amman\n\* `Asia\/Anadyr` - Asia\/Anadyr\n\* `Asia\/Aqtau` - Asia\/Aqtau\n\* `Asia\/Aqtobe` - Asia\/Aqtobe\n\* `Asia\/Ashgabat` - Asia\/Ashgabat\n\* `Asia\/Ashkhabad` - Asia\/Ashkhabad\n\* `Asia\/Atyrau` - Asia\/Atyrau\n\* `Asia\/Baghdad` - Asia\/Baghdad\n\* `Asia\/Bahrain` - Asia\/Bahrain\n\* `Asia\/Baku` - Asia\/Baku\n\* `Asia\/Bangkok` - Asia\/Bangkok\n\* `Asia\/Barnaul` - Asia\/Barnaul\n\* `Asia\/Beirut` - Asia\/Beirut\n\* `Asia\/Bishkek` - Asia\/Bishkek\n\* `Asia\/Brunei` - Asia\/Brunei\n\* `Asia\/Calcutta` - Asia\/Calcutta\n\* `Asia\/Chita` - Asia\/Chita\n\* `Asia\/Choibalsan` - Asia\/Choibalsan\n\* `Asia\/Chongqing` - Asia\/Chongqing\n\* `Asia\/Chungking` - Asia\/Chungking\n\* `Asia\/Colombo` - Asia\/Colombo\n\* `Asia\/Dacca` - Asia\/Dacca\n\* `Asia\/Damascus` - Asia\/Damascus\n\* `Asia\/Dhaka` - Asia\/Dhaka\n\* `Asia\/Dili` - Asia\/Dili\n\* `Asia\/Dubai` - Asia\/Dubai\n\* `Asia\/Dushanbe` - Asia\/Dushanbe\n\* `Asia\/Famagusta` - Asia\/Famagusta\n\* `Asia\/Gaza` - Asia\/Gaza\n\* `Asia\/Harbin` - Asia\/Harbin\n\* `Asia\/Hebron` - Asia\/Hebron\n\* `Asia\/Ho_Chi_Minh` - Asia\/Ho_Chi_Minh\n\* `Asia\/Hong_Kong` - Asia\/Hong_Kong\n\* `Asia\/Hovd` - Asia\/Hovd\n\* `Asia\/Irkutsk` - Asia\/Irkutsk\n\* `Asia\/Istanbul` - Asia\/Istanbul\n\* `Asia\/Jakarta` - Asia\/Jakarta\n\* `Asia\/Jayapura` - Asia\/Jayapura\n\* `Asia\/Jerusalem` - Asia\/Jerusalem\n\* `Asia\/Kabul` - Asia\/Kabul\n\* `Asia\/Kamchatka` - Asia\/Kamchatka\n\* `Asia\/Karachi` - Asia\/Karachi\n\* `Asia\/Kashgar` - Asia\/Kashgar\n\* `Asia\/Kathmandu` - Asia\/Kathmandu\n\* `Asia\/Katmandu` - Asia\/Katmandu\n\* `Asia\/Khandyga` - Asia\/Khandyga\n\* `Asia\/Kolkata` - Asia\/Kolkata\n\* `Asia\/Krasnoyarsk` - Asia\/Krasnoyarsk\n\* `Asia\/Kuala_Lumpur` - Asia\/Kuala_Lumpur\n\* `Asia\/Kuching` - Asia\/Kuching\n\* `Asia\/Kuwait` - Asia\/Kuwait\n\* `Asia\/Macao` - Asia\/Macao\n\* `Asia\/Macau` - Asia\/Macau\n\* `Asia\/Magadan` - Asia\/Magadan\n\* `Asia\/Makassar` - Asia\/Makassar\n\* `Asia\/Manila` - Asia\/Manila\n\* `Asia\/Muscat` - Asia\/Muscat\n\* `Asia\/Nicosia` - Asia\/Nicosia\n\* `Asia\/Novokuznetsk` - Asia\/Novokuznetsk\n\* `Asia\/Novosibirsk` - Asia\/Novosibirsk\n\* `Asia\/Omsk` - Asia\/Omsk\n\* `Asia\/Oral` - Asia\/Oral\n\* `Asia\/Phnom_Penh` - Asia\/Phnom_Penh\n\* `Asia\/Pontianak` - Asia\/Pontianak\n\* `Asia\/Pyongyang` - Asia\/Pyongyang\n\* `Asia\/Qatar` - Asia\/Qatar\n\* `Asia\/Qostanay` - Asia\/Qostanay\n\* `Asia\/Qyzylorda` - Asia\/Qyzylorda\n\* `Asia\/Rangoon` - Asia\/Rangoon\n\* `Asia\/Riyadh` - Asia\/Riyadh\n\* `Asia\/Saigon` - Asia\/Saigon\n\* `Asia\/Sakhalin` - Asia\/Sakhalin\n\* `Asia\/Samarkand` - Asia\/Samarkand\n\* `Asia\/Seoul` - Asia\/Seoul\n\* `Asia\/Shanghai` - Asia\/Shanghai\n\* `Asia\/Singapore` - Asia\/Singapore\n\* `Asia\/Srednekolymsk` - Asia\/Srednekolymsk\n\* `Asia\/Taipei` - Asia\/Taipei\n\* `Asia\/Tashkent` - Asia\/Tashkent\n\* `Asia\/Tbilisi` - Asia\/Tbilisi\n\* `Asia\/Tehran` - Asia\/Tehran\n\* `Asia\/Tel_Aviv` - Asia\/Tel_Aviv\n\* `Asia\/Thimbu` - Asia\/Thimbu\n\* `Asia\/Thimphu` - Asia\/Thimphu\n\* `Asia\/Tokyo` - Asia\/Tokyo\n\* `Asia\/Tomsk` - Asia\/Tomsk\n\* `Asia\/Ujung_Pandang` - Asia\/Ujung_Pandang\n\* `Asia\/Ulaanbaatar` - Asia\/Ulaanbaatar\n\* `Asia\/Ulan_Bator` - Asia\/Ulan_Bator\n\* `Asia\/Urumqi` - Asia\/Urumqi\n\* `Asia\/Ust-Nera` - Asia\/Ust-Nera\n\* `Asia\/Vientiane` - Asia\/Vientiane\n\* `Asia\/Vladivostok` - Asia\/Vladivostok\n\* `Asia\/Yakutsk` - Asia\/Yakutsk\n\* `Asia\/Yangon` - Asia\/Yangon\n\* `Asia\/Yekaterinburg` - Asia\/Yekaterinburg\n\* `Asia\/Yerevan` - Asia\/Yerevan\n\* `Atlantic\/Azores` - Atlantic\/Azores\n\* `Atlantic\/Bermuda` - Atlantic\/Bermuda\n\* `Atlantic\/Canary` - Atlantic\/Canary\n\* `Atlantic\/Cape_Verde` - Atlantic\/Cape_Verde\n\* `Atlantic\/Faeroe` - Atlantic\/Faeroe\n\* `Atlantic\/Faroe` - Atlantic\/Faroe\n\* `Atlantic\/Jan_Mayen` - Atlantic\/Jan_Mayen\n\* `Atlantic\/Madeira` - Atlantic\/Madeira\n\* `Atlantic\/Reykjavik` - Atlantic\/Reykjavik\n\* `Atlantic\/South_Georgia` - Atlantic\/South_Georgia\n\* `Atlantic\/St_Helena` - Atlantic\/St_Helena\n\* `Atlantic\/Stanley` - Atlantic\/Stanley\n\* `Australia\/ACT` - Australia\/ACT\n\* `Australia\/Adelaide` - Australia\/Adelaide\n\* `Australia\/Brisbane` - Australia\/Brisbane\n\* `Australia\/Broken_Hill` - Australia\/Broken_Hill\n\* `Australia\/Canberra` - Australia\/Canberra\n\* `Australia\/Currie` - Australia\/Currie\n\* `Australia\/Darwin` - Australia\/Darwin\n\* `Australia\/Eucla` - Australia\/Eucla\n\* `Australia\/Hobart` - Australia\/Hobart\n\* `Australia\/LHI` - Australia\/LHI\n\* `Australia\/Lindeman` - Australia\/Lindeman\n\* `Australia\/Lord_Howe` - Australia\/Lord_Howe\n\* `Australia\/Melbourne` - Australia\/Melbourne\n\* `Australia\/NSW` - Australia\/NSW\n\* `Australia\/North` - Australia\/North\n\* `Australia\/Perth` - Australia\/Perth\n\* `Australia\/Queensland` - Australia\/Queensland\n\* `Australia\/South` - Australia\/South\n\* `Australia\/Sydney` - Australia\/Sydney\n\* `Australia\/Tasmania` - Australia\/Tasmania\n\* `Australia\/Victoria` - Australia\/Victoria\n\* `Australia\/West` - Australia\/West\n\* `Australia\/Yancowinna` - Australia\/Yancowinna\n\* `Brazil\/Acre` - Brazil\/Acre\n\* `Brazil\/DeNoronha` - Brazil\/DeNoronha\n\* `Brazil\/East` - Brazil\/East\n\* `Brazil\/West` - Brazil\/West\n\* `CET` - CET\n\* `CST6CDT` - CST6CDT\n\* `Canada\/Atlantic` - Canada\/Atlantic\n\* `Canada\/Central` - Canada\/Central\n\* `Canada\/Eastern` - Canada\/Eastern\n\* `Canada\/Mountain` - Canada\/Mountain\n\* `Canada\/Newfoundland` - Canada\/Newfoundland\n\* `Canada\/Pacific` - Canada\/Pacific\n\* `Canada\/Saskatchewan` - Canada\/Saskatchewan\n\* `Canada\/Yukon` - Canada\/Yukon\n\* `Chile\/Continental` - Chile\/Continental\n\* `Chile\/EasterIsland` - Chile\/EasterIsland\n\* `Cuba` - Cuba\n\* `EET` - EET\n\* `EST` - EST\n\* `EST5EDT` - EST5EDT\n\* `Egypt` - Egypt\n\* `Eire` - Eire\n\* `Etc\/GMT` - Etc\/GMT\n\* `Etc\/GMT+0` - Etc\/GMT+0\n\* `Etc\/GMT+1` - Etc\/GMT+1\n\* `Etc\/GMT+10` - Etc\/GMT+10\n\* `Etc\/GMT+11` - Etc\/GMT+11\n\* `Etc\/GMT+12` - Etc\/GMT+12\n\* `Etc\/GMT+2` - Etc\/GMT+2\n\* `Etc\/GMT+3` - Etc\/GMT+3\n\* `Etc\/GMT+4` - Etc\/GMT+4\n\* `Etc\/GMT+5` - Etc\/GMT+5\n\* `Etc\/GMT+6` - Etc\/GMT+6\n\* `Etc\/GMT+7` - Etc\/GMT+7\n\* `Etc\/GMT+8` - Etc\/GMT+8\n\* `Etc\/GMT+9` - Etc\/GMT+9\n\* `Etc\/GMT-0` - Etc\/GMT-0\n\* `Etc\/GMT-1` - Etc\/GMT-1\n\* `Etc\/GMT-10` - Etc\/GMT-10\n\* `Etc\/GMT-11` - Etc\/GMT-11\n\* `Etc\/GMT-12` - Etc\/GMT-12\n\* `Etc\/GMT-13` - Etc\/GMT-13\n\* `Etc\/GMT-14` - Etc\/GMT-14\n\* `Etc\/GMT-2` - Etc\/GMT-2\n\* `Etc\/GMT-3` - Etc\/GMT-3\n\* `Etc\/GMT-4` - Etc\/GMT-4\n\* `Etc\/GMT-5` - Etc\/GMT-5\n\* `Etc\/GMT-6` - Etc\/GMT-6\n\* `Etc\/GMT-7` - Etc\/GMT-7\n\* `Etc\/GMT-8` - Etc\/GMT-8\n\* `Etc\/GMT-9` - Etc\/GMT-9\n\* `Etc\/GMT0` - Etc\/GMT0\n\* `Etc\/Greenwich` - Etc\/Greenwich\n\* `Etc\/UCT` - Etc\/UCT\n\* `Etc\/UTC` - Etc\/UTC\n\* `Etc\/Universal` - Etc\/Universal\n\* `Etc\/Zulu` - Etc\/Zulu\n\* `Europe\/Amsterdam` - Europe\/Amsterdam\n\* `Europe\/Andorra` - Europe\/Andorra\n\* `Europe\/Astrakhan` - Europe\/Astrakhan\n\* `Europe\/Athens` - Europe\/Athens\n\* `Europe\/Belfast` - Europe\/Belfast\n\* `Europe\/Belgrade` - Europe\/Belgrade\n\* `Europe\/Berlin` - Europe\/Berlin\n\* `Europe\/Bratislava` - Europe\/Bratislava\n\* `Europe\/Brussels` - Europe\/Brussels\n\* `Europe\/Bucharest` - Europe\/Bucharest\n\* `Europe\/Budapest` - Europe\/Budapest\n\* `Europe\/Busingen` - Europe\/Busingen\n\* `Europe\/Chisinau` - Europe\/Chisinau\n\* `Europe\/Copenhagen` - Europe\/Copenhagen\n\* `Europe\/Dublin` - Europe\/Dublin\n\* `Europe\/Gibraltar` - Europe\/Gibraltar\n\* `Europe\/Guernsey` - Europe\/Guernsey\n\* `Europe\/Helsinki` - Europe\/Helsinki\n\* `Europe\/Isle_of_Man` - Europe\/Isle_of_Man\n\* `Europe\/Istanbul` - Europe\/Istanbul\n\* `Europe\/Jersey` - Europe\/Jersey\n\* `Europe\/Kaliningrad` - Europe\/Kaliningrad\n\* `Europe\/Kiev` - Europe\/Kiev\n\* `Europe\/Kirov` - Europe\/Kirov\n\* `Europe\/Kyiv` - Europe\/Kyiv\n\* `Europe\/Lisbon` - Europe\/Lisbon\n\* `Europe\/Ljubljana` - Europe\/Ljubljana\n\* `Europe\/London` - Europe\/London\n\* `Europe\/Luxembourg` - Europe\/Luxembourg\n\* `Europe\/Madrid` - Europe\/Madrid\n\* `Europe\/Malta` - Europe\/Malta\n\* `Europe\/Mariehamn` - Europe\/Mariehamn\n\* `Europe\/Minsk` - Europe\/Minsk\n\* `Europe\/Monaco` - Europe\/Monaco\n\* `Europe\/Moscow` - Europe\/Moscow\n\* `Europe\/Nicosia` - Europe\/Nicosia\n\* `Europe\/Oslo` - Europe\/Oslo\n\* `Europe\/Paris` - Europe\/Paris\n\* `Europe\/Podgorica` - Europe\/Podgorica\n\* `Europe\/Prague` - Europe\/Prague\n\* `Europe\/Riga` - Europe\/Riga\n\* `Europe\/Rome` - Europe\/Rome\n\* `Europe\/Samara` - Europe\/Samara\n\* `Europe\/San_Marino` - Europe\/San_Marino\n\* `Europe\/Sarajevo` - Europe\/Sarajevo\n\* `Europe\/Saratov` - Europe\/Saratov\n\* `Europe\/Simferopol` - Europe\/Simferopol\n\* `Europe\/Skopje` - Europe\/Skopje\n\* `Europe\/Sofia` - Europe\/Sofia\n\* `Europe\/Stockholm` - Europe\/Stockholm\n\* `Europe\/Tallinn` - Europe\/Tallinn\n\* `Europe\/Tirane` - Europe\/Tirane\n\* `Europe\/Tiraspol` - Europe\/Tiraspol\n\* `Europe\/Ulyanovsk` - Europe\/Ulyanovsk\n\* `Europe\/Uzhgorod` - Europe\/Uzhgorod\n\* `Europe\/Vaduz` - Europe\/Vaduz\n\* `Europe\/Vatican` - Europe\/Vatican\n\* `Europe\/Vienna` - Europe\/Vienna\n\* `Europe\/Vilnius` - Europe\/Vilnius\n\* `Europe\/Volgograd` - Europe\/Volgograd\n\* `Europe\/Warsaw` - Europe\/Warsaw\n\* `Europe\/Zagreb` - Europe\/Zagreb\n\* `Europe\/Zaporozhye` - Europe\/Zaporozhye\n\* `Europe\/Zurich` - Europe\/Zurich\n\* `GB` - GB\n\* `GB-Eire` - GB-Eire\n\* `GMT` - GMT\n\* `GMT+0` - GMT+0\n\* `GMT-0` - GMT-0\n\* `GMT0` - GMT0\n\* `Greenwich` - Greenwich\n\* `HST` - HST\n\* `Hongkong` - Hongkong\n\* `Iceland` - Iceland\n\* `Indian\/Antananarivo` - Indian\/Antananarivo\n\* `Indian\/Chagos` - Indian\/Chagos\n\* `Indian\/Christmas` - Indian\/Christmas\n\* `Indian\/Cocos` - Indian\/Cocos\n\* `Indian\/Comoro` - Indian\/Comoro\n\* `Indian\/Kerguelen` - Indian\/Kerguelen\n\* `Indian\/Mahe` - Indian\/Mahe\n\* `Indian\/Maldives` - Indian\/Maldives\n\* `Indian\/Mauritius` - Indian\/Mauritius\n\* `Indian\/Mayotte` - Indian\/Mayotte\n\* `Indian\/Reunion` - Indian\/Reunion\n\* `Iran` - Iran\n\* `Israel` - Israel\n\* `Jamaica` - Jamaica\n\* `Japan` - Japan\n\* `Kwajalein` - Kwajalein\n\* `Libya` - Libya\n\* `MET` - MET\n\* `MST` - MST\n\* `MST7MDT` - MST7MDT\n\* `Mexico\/BajaNorte` - Mexico\/BajaNorte\n\* `Mexico\/BajaSur` - Mexico\/BajaSur\n\* `Mexico\/General` - Mexico\/General\n\* `NZ` - NZ\n\* `NZ-CHAT` - NZ-CHAT\n\* `Navajo` - Navajo\n\* `PRC` - PRC\n\* `PST8PDT` - PST8PDT\n\* `Pacific\/Apia` - Pacific\/Apia\n\* `Pacific\/Auckland` - Pacific\/Auckland\n\* `Pacific\/Bougainville` - Pacific\/Bougainville\n\* `Pacific\/Chatham` - Pacific\/Chatham\n\* `Pacific\/Chuuk` - Pacific\/Chuuk\n\* `Pacific\/Easter` - Pacific\/Easter\n\* `Pacific\/Efate` - Pacific\/Efate\n\* `Pacific\/Enderbury` - Pacific\/Enderbury\n\* `Pacific\/Fakaofo` - Pacific\/Fakaofo\n\* `Pacific\/Fiji` - Pacific\/Fiji\n\* `Pacific\/Funafuti` - Pacific\/Funafuti\n\* `Pacific\/Galapagos` - Pacific\/Galapagos\n\* `Pacific\/Gambier` - Pacific\/Gambier\n\* `Pacific\/Guadalcanal` - Pacific\/Guadalcanal\n\* `Pacific\/Guam` - Pacific\/Guam\n\* `Pacific\/Honolulu` - Pacific\/Honolulu\n\* `Pacific\/Johnston` - Pacific\/Johnston\n\* `Pacific\/Kanton` - Pacific\/Kanton\n\* `Pacific\/Kiritimati` - Pacific\/Kiritimati\n\* `Pacific\/Kosrae` - Pacific\/Kosrae\n\* `Pacific\/Kwajalein` - Pacific\/Kwajalein\n\* `Pacific\/Majuro` - Pacific\/Majuro\n\* `Pacific\/Marquesas` - Pacific\/Marquesas\n\* `Pacific\/Midway` - Pacific\/Midway\n\* `Pacific\/Nauru` - Pacific\/Nauru\n\* `Pacific\/Niue` - Pacific\/Niue\n\* `Pacific\/Norfolk` - Pacific\/Norfolk\n\* `Pacific\/Noumea` - Pacific\/Noumea\n\* `Pacific\/Pago_Pago` - Pacific\/Pago_Pago\n\* `Pacific\/Palau` - Pacific\/Palau\n\* `Pacific\/Pitcairn` - Pacific\/Pitcairn\n\* `Pacific\/Pohnpei` - Pacific\/Pohnpei\n\* `Pacific\/Ponape` - Pacific\/Ponape\n\* `Pacific\/Port_Moresby` - Pacific\/Port_Moresby\n\* `Pacific\/Rarotonga` - Pacific\/Rarotonga\n\* `Pacific\/Saipan` - Pacific\/Saipan\n\* `Pacific\/Samoa` - Pacific\/Samoa\n\* `Pacific\/Tahiti` - Pacific\/Tahiti\n\* `Pacific\/Tarawa` - Pacific\/Tarawa\n\* `Pacific\/Tongatapu` - Pacific\/Tongatapu\n\* `Pacific\/Truk` - Pacific\/Truk\n\* `Pacific\/Wake` - Pacific\/Wake\n\* `Pacific\/Wallis` - Pacific\/Wallis\n\* `Pacific\/Yap` - Pacific\/Yap\n\* `Poland` - Poland\n\* `Portugal` - Portugal\n\* `ROC` - ROC\n\* `ROK` - ROK\n\* `Singapore` - Singapore\n\* `Turkey` - Turkey\n\* `UCT` - UCT\n\* `US\/Alaska` - US\/Alaska\n\* `US\/Aleutian` - US\/Aleutian\n\* `US\/Arizona` - US\/Arizona\n\* `US\/Central` - US\/Central\n\* `US\/East-Indiana` - US\/East-Indiana\n\* `US\/Eastern` - US\/Eastern\n\* `US\/Hawaii` - US\/Hawaii\n\* `US\/Indiana-Starke` - US\/Indiana-Starke\n\* `US\/Michigan` - US\/Michigan\n\* `US\/Mountain` - US\/Mountain\n\* `US\/Pacific` - US\/Pacific\n\* `US\/Samoa` - US\/Samoa\n\* `UTC` - UTC\n\* `Universal` - Universal\n\* `W-SU` - W-SU\n\* `WET` - WET\n\* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(
                zod.string().max(organizationsProjectsChangeOrganizationCreateBodyPersonDisplayNamePropertiesItemMax)
            )
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat('decimal', organizationsProjectsChangeOrganizationCreateBodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(organizationsProjectsChangeOrganizationCreateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(organizationsProjectsChangeOrganizationCreateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(organizationsProjectsChangeOrganizationCreateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('\* `0` - Sunday\n\* `1` - Monday'),
                zod.null(),
            ])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n\* `0` - Sunday\n\* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(
                zod.string().max(organizationsProjectsChangeOrganizationCreateBodyRecordingDomainsItemMax).nullable()
            )
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations \/ live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(
                        organizationsProjectsChangeOrganizationCreateBodyMarketingAnalyticsConfigAttributionWindowDaysMax
                    )
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsChangeOrganizationCreateBodyDefaultDataThemeMin)
            .max(organizationsProjectsChangeOrganizationCreateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Projects for the current organization.
 */
export const organizationsProjectsCompleteProductOnboardingPartialUpdateBodyNameMax = 200

export const organizationsProjectsCompleteProductOnboardingPartialUpdateBodyProductDescriptionMax = 1000

export const organizationsProjectsCompleteProductOnboardingPartialUpdateBodyAppUrlsItemMax = 200

export const organizationsProjectsCompleteProductOnboardingPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsCompleteProductOnboardingPartialUpdateBodySessionRecordingSampleRateRegExp =
    new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const organizationsProjectsCompleteProductOnboardingPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsCompleteProductOnboardingPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsCompleteProductOnboardingPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsCompleteProductOnboardingPartialUpdateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsCompleteProductOnboardingPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsCompleteProductOnboardingPartialUpdateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsCompleteProductOnboardingPartialUpdateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsCompleteProductOnboardingPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsCompleteProductOnboardingPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsCompleteProductOnboardingPartialUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsCompleteProductOnboardingPartialUpdateBodyAppUrlsItemMax)
                    .nullable()
            )
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal\/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal\/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America\/Los_Angeles`).\n\n\* `Africa\/Abidjan` - Africa\/Abidjan\n\* `Africa\/Accra` - Africa\/Accra\n\* `Africa\/Addis_Ababa` - Africa\/Addis_Ababa\n\* `Africa\/Algiers` - Africa\/Algiers\n\* `Africa\/Asmara` - Africa\/Asmara\n\* `Africa\/Asmera` - Africa\/Asmera\n\* `Africa\/Bamako` - Africa\/Bamako\n\* `Africa\/Bangui` - Africa\/Bangui\n\* `Africa\/Banjul` - Africa\/Banjul\n\* `Africa\/Bissau` - Africa\/Bissau\n\* `Africa\/Blantyre` - Africa\/Blantyre\n\* `Africa\/Brazzaville` - Africa\/Brazzaville\n\* `Africa\/Bujumbura` - Africa\/Bujumbura\n\* `Africa\/Cairo` - Africa\/Cairo\n\* `Africa\/Casablanca` - Africa\/Casablanca\n\* `Africa\/Ceuta` - Africa\/Ceuta\n\* `Africa\/Conakry` - Africa\/Conakry\n\* `Africa\/Dakar` - Africa\/Dakar\n\* `Africa\/Dar_es_Salaam` - Africa\/Dar_es_Salaam\n\* `Africa\/Djibouti` - Africa\/Djibouti\n\* `Africa\/Douala` - Africa\/Douala\n\* `Africa\/El_Aaiun` - Africa\/El_Aaiun\n\* `Africa\/Freetown` - Africa\/Freetown\n\* `Africa\/Gaborone` - Africa\/Gaborone\n\* `Africa\/Harare` - Africa\/Harare\n\* `Africa\/Johannesburg` - Africa\/Johannesburg\n\* `Africa\/Juba` - Africa\/Juba\n\* `Africa\/Kampala` - Africa\/Kampala\n\* `Africa\/Khartoum` - Africa\/Khartoum\n\* `Africa\/Kigali` - Africa\/Kigali\n\* `Africa\/Kinshasa` - Africa\/Kinshasa\n\* `Africa\/Lagos` - Africa\/Lagos\n\* `Africa\/Libreville` - Africa\/Libreville\n\* `Africa\/Lome` - Africa\/Lome\n\* `Africa\/Luanda` - Africa\/Luanda\n\* `Africa\/Lubumbashi` - Africa\/Lubumbashi\n\* `Africa\/Lusaka` - Africa\/Lusaka\n\* `Africa\/Malabo` - Africa\/Malabo\n\* `Africa\/Maputo` - Africa\/Maputo\n\* `Africa\/Maseru` - Africa\/Maseru\n\* `Africa\/Mbabane` - Africa\/Mbabane\n\* `Africa\/Mogadishu` - Africa\/Mogadishu\n\* `Africa\/Monrovia` - Africa\/Monrovia\n\* `Africa\/Nairobi` - Africa\/Nairobi\n\* `Africa\/Ndjamena` - Africa\/Ndjamena\n\* `Africa\/Niamey` - Africa\/Niamey\n\* `Africa\/Nouakchott` - Africa\/Nouakchott\n\* `Africa\/Ouagadougou` - Africa\/Ouagadougou\n\* `Africa\/Porto-Novo` - Africa\/Porto-Novo\n\* `Africa\/Sao_Tome` - Africa\/Sao_Tome\n\* `Africa\/Timbuktu` - Africa\/Timbuktu\n\* `Africa\/Tripoli` - Africa\/Tripoli\n\* `Africa\/Tunis` - Africa\/Tunis\n\* `Africa\/Windhoek` - Africa\/Windhoek\n\* `America\/Adak` - America\/Adak\n\* `America\/Anchorage` - America\/Anchorage\n\* `America\/Anguilla` - America\/Anguilla\n\* `America\/Antigua` - America\/Antigua\n\* `America\/Araguaina` - America\/Araguaina\n\* `America\/Argentina\/Buenos_Aires` - America\/Argentina\/Buenos_Aires\n\* `America\/Argentina\/Catamarca` - America\/Argentina\/Catamarca\n\* `America\/Argentina\/ComodRivadavia` - America\/Argentina\/ComodRivadavia\n\* `America\/Argentina\/Cordoba` - America\/Argentina\/Cordoba\n\* `America\/Argentina\/Jujuy` - America\/Argentina\/Jujuy\n\* `America\/Argentina\/La_Rioja` - America\/Argentina\/La_Rioja\n\* `America\/Argentina\/Mendoza` - America\/Argentina\/Mendoza\n\* `America\/Argentina\/Rio_Gallegos` - America\/Argentina\/Rio_Gallegos\n\* `America\/Argentina\/Salta` - America\/Argentina\/Salta\n\* `America\/Argentina\/San_Juan` - America\/Argentina\/San_Juan\n\* `America\/Argentina\/San_Luis` - America\/Argentina\/San_Luis\n\* `America\/Argentina\/Tucuman` - America\/Argentina\/Tucuman\n\* `America\/Argentina\/Ushuaia` - America\/Argentina\/Ushuaia\n\* `America\/Aruba` - America\/Aruba\n\* `America\/Asuncion` - America\/Asuncion\n\* `America\/Atikokan` - America\/Atikokan\n\* `America\/Atka` - America\/Atka\n\* `America\/Bahia` - America\/Bahia\n\* `America\/Bahia_Banderas` - America\/Bahia_Banderas\n\* `America\/Barbados` - America\/Barbados\n\* `America\/Belem` - America\/Belem\n\* `America\/Belize` - America\/Belize\n\* `America\/Blanc-Sablon` - America\/Blanc-Sablon\n\* `America\/Boa_Vista` - America\/Boa_Vista\n\* `America\/Bogota` - America\/Bogota\n\* `America\/Boise` - America\/Boise\n\* `America\/Buenos_Aires` - America\/Buenos_Aires\n\* `America\/Cambridge_Bay` - America\/Cambridge_Bay\n\* `America\/Campo_Grande` - America\/Campo_Grande\n\* `America\/Cancun` - America\/Cancun\n\* `America\/Caracas` - America\/Caracas\n\* `America\/Catamarca` - America\/Catamarca\n\* `America\/Cayenne` - America\/Cayenne\n\* `America\/Cayman` - America\/Cayman\n\* `America\/Chicago` - America\/Chicago\n\* `America\/Chihuahua` - America\/Chihuahua\n\* `America\/Ciudad_Juarez` - America\/Ciudad_Juarez\n\* `America\/Coral_Harbour` - America\/Coral_Harbour\n\* `America\/Cordoba` - America\/Cordoba\n\* `America\/Costa_Rica` - America\/Costa_Rica\n\* `America\/Creston` - America\/Creston\n\* `America\/Cuiaba` - America\/Cuiaba\n\* `America\/Curacao` - America\/Curacao\n\* `America\/Danmarkshavn` - America\/Danmarkshavn\n\* `America\/Dawson` - America\/Dawson\n\* `America\/Dawson_Creek` - America\/Dawson_Creek\n\* `America\/Denver` - America\/Denver\n\* `America\/Detroit` - America\/Detroit\n\* `America\/Dominica` - America\/Dominica\n\* `America\/Edmonton` - America\/Edmonton\n\* `America\/Eirunepe` - America\/Eirunepe\n\* `America\/El_Salvador` - America\/El_Salvador\n\* `America\/Ensenada` - America\/Ensenada\n\* `America\/Fort_Nelson` - America\/Fort_Nelson\n\* `America\/Fort_Wayne` - America\/Fort_Wayne\n\* `America\/Fortaleza` - America\/Fortaleza\n\* `America\/Glace_Bay` - America\/Glace_Bay\n\* `America\/Godthab` - America\/Godthab\n\* `America\/Goose_Bay` - America\/Goose_Bay\n\* `America\/Grand_Turk` - America\/Grand_Turk\n\* `America\/Grenada` - America\/Grenada\n\* `America\/Guadeloupe` - America\/Guadeloupe\n\* `America\/Guatemala` - America\/Guatemala\n\* `America\/Guayaquil` - America\/Guayaquil\n\* `America\/Guyana` - America\/Guyana\n\* `America\/Halifax` - America\/Halifax\n\* `America\/Havana` - America\/Havana\n\* `America\/Hermosillo` - America\/Hermosillo\n\* `America\/Indiana\/Indianapolis` - America\/Indiana\/Indianapolis\n\* `America\/Indiana\/Knox` - America\/Indiana\/Knox\n\* `America\/Indiana\/Marengo` - America\/Indiana\/Marengo\n\* `America\/Indiana\/Petersburg` - America\/Indiana\/Petersburg\n\* `America\/Indiana\/Tell_City` - America\/Indiana\/Tell_City\n\* `America\/Indiana\/Vevay` - America\/Indiana\/Vevay\n\* `America\/Indiana\/Vincennes` - America\/Indiana\/Vincennes\n\* `America\/Indiana\/Winamac` - America\/Indiana\/Winamac\n\* `America\/Indianapolis` - America\/Indianapolis\n\* `America\/Inuvik` - America\/Inuvik\n\* `America\/Iqaluit` - America\/Iqaluit\n\* `America\/Jamaica` - America\/Jamaica\n\* `America\/Jujuy` - America\/Jujuy\n\* `America\/Juneau` - America\/Juneau\n\* `America\/Kentucky\/Louisville` - America\/Kentucky\/Louisville\n\* `America\/Kentucky\/Monticello` - America\/Kentucky\/Monticello\n\* `America\/Knox_IN` - America\/Knox_IN\n\* `America\/Kralendijk` - America\/Kralendijk\n\* `America\/La_Paz` - America\/La_Paz\n\* `America\/Lima` - America\/Lima\n\* `America\/Los_Angeles` - America\/Los_Angeles\n\* `America\/Louisville` - America\/Louisville\n\* `America\/Lower_Princes` - America\/Lower_Princes\n\* `America\/Maceio` - America\/Maceio\n\* `America\/Managua` - America\/Managua\n\* `America\/Manaus` - America\/Manaus\n\* `America\/Marigot` - America\/Marigot\n\* `America\/Martinique` - America\/Martinique\n\* `America\/Matamoros` - America\/Matamoros\n\* `America\/Mazatlan` - America\/Mazatlan\n\* `America\/Mendoza` - America\/Mendoza\n\* `America\/Menominee` - America\/Menominee\n\* `America\/Merida` - America\/Merida\n\* `America\/Metlakatla` - America\/Metlakatla\n\* `America\/Mexico_City` - America\/Mexico_City\n\* `America\/Miquelon` - America\/Miquelon\n\* `America\/Moncton` - America\/Moncton\n\* `America\/Monterrey` - America\/Monterrey\n\* `America\/Montevideo` - America\/Montevideo\n\* `America\/Montreal` - America\/Montreal\n\* `America\/Montserrat` - America\/Montserrat\n\* `America\/Nassau` - America\/Nassau\n\* `America\/New_York` - America\/New_York\n\* `America\/Nipigon` - America\/Nipigon\n\* `America\/Nome` - America\/Nome\n\* `America\/Noronha` - America\/Noronha\n\* `America\/North_Dakota\/Beulah` - America\/North_Dakota\/Beulah\n\* `America\/North_Dakota\/Center` - America\/North_Dakota\/Center\n\* `America\/North_Dakota\/New_Salem` - America\/North_Dakota\/New_Salem\n\* `America\/Nuuk` - America\/Nuuk\n\* `America\/Ojinaga` - America\/Ojinaga\n\* `America\/Panama` - America\/Panama\n\* `America\/Pangnirtung` - America\/Pangnirtung\n\* `America\/Paramaribo` - America\/Paramaribo\n\* `America\/Phoenix` - America\/Phoenix\n\* `America\/Port-au-Prince` - America\/Port-au-Prince\n\* `America\/Port_of_Spain` - America\/Port_of_Spain\n\* `America\/Porto_Acre` - America\/Porto_Acre\n\* `America\/Porto_Velho` - America\/Porto_Velho\n\* `America\/Puerto_Rico` - America\/Puerto_Rico\n\* `America\/Punta_Arenas` - America\/Punta_Arenas\n\* `America\/Rainy_River` - America\/Rainy_River\n\* `America\/Rankin_Inlet` - America\/Rankin_Inlet\n\* `America\/Recife` - America\/Recife\n\* `America\/Regina` - America\/Regina\n\* `America\/Resolute` - America\/Resolute\n\* `America\/Rio_Branco` - America\/Rio_Branco\n\* `America\/Rosario` - America\/Rosario\n\* `America\/Santa_Isabel` - America\/Santa_Isabel\n\* `America\/Santarem` - America\/Santarem\n\* `America\/Santiago` - America\/Santiago\n\* `America\/Santo_Domingo` - America\/Santo_Domingo\n\* `America\/Sao_Paulo` - America\/Sao_Paulo\n\* `America\/Scoresbysund` - America\/Scoresbysund\n\* `America\/Shiprock` - America\/Shiprock\n\* `America\/Sitka` - America\/Sitka\n\* `America\/St_Barthelemy` - America\/St_Barthelemy\n\* `America\/St_Johns` - America\/St_Johns\n\* `America\/St_Kitts` - America\/St_Kitts\n\* `America\/St_Lucia` - America\/St_Lucia\n\* `America\/St_Thomas` - America\/St_Thomas\n\* `America\/St_Vincent` - America\/St_Vincent\n\* `America\/Swift_Current` - America\/Swift_Current\n\* `America\/Tegucigalpa` - America\/Tegucigalpa\n\* `America\/Thule` - America\/Thule\n\* `America\/Thunder_Bay` - America\/Thunder_Bay\n\* `America\/Tijuana` - America\/Tijuana\n\* `America\/Toronto` - America\/Toronto\n\* `America\/Tortola` - America\/Tortola\n\* `America\/Vancouver` - America\/Vancouver\n\* `America\/Virgin` - America\/Virgin\n\* `America\/Whitehorse` - America\/Whitehorse\n\* `America\/Winnipeg` - America\/Winnipeg\n\* `America\/Yakutat` - America\/Yakutat\n\* `America\/Yellowknife` - America\/Yellowknife\n\* `Antarctica\/Casey` - Antarctica\/Casey\n\* `Antarctica\/Davis` - Antarctica\/Davis\n\* `Antarctica\/DumontDUrville` - Antarctica\/DumontDUrville\n\* `Antarctica\/Macquarie` - Antarctica\/Macquarie\n\* `Antarctica\/Mawson` - Antarctica\/Mawson\n\* `Antarctica\/McMurdo` - Antarctica\/McMurdo\n\* `Antarctica\/Palmer` - Antarctica\/Palmer\n\* `Antarctica\/Rothera` - Antarctica\/Rothera\n\* `Antarctica\/South_Pole` - Antarctica\/South_Pole\n\* `Antarctica\/Syowa` - Antarctica\/Syowa\n\* `Antarctica\/Troll` - Antarctica\/Troll\n\* `Antarctica\/Vostok` - Antarctica\/Vostok\n\* `Arctic\/Longyearbyen` - Arctic\/Longyearbyen\n\* `Asia\/Aden` - Asia\/Aden\n\* `Asia\/Almaty` - Asia\/Almaty\n\* `Asia\/Amman` - Asia\/Amman\n\* `Asia\/Anadyr` - Asia\/Anadyr\n\* `Asia\/Aqtau` - Asia\/Aqtau\n\* `Asia\/Aqtobe` - Asia\/Aqtobe\n\* `Asia\/Ashgabat` - Asia\/Ashgabat\n\* `Asia\/Ashkhabad` - Asia\/Ashkhabad\n\* `Asia\/Atyrau` - Asia\/Atyrau\n\* `Asia\/Baghdad` - Asia\/Baghdad\n\* `Asia\/Bahrain` - Asia\/Bahrain\n\* `Asia\/Baku` - Asia\/Baku\n\* `Asia\/Bangkok` - Asia\/Bangkok\n\* `Asia\/Barnaul` - Asia\/Barnaul\n\* `Asia\/Beirut` - Asia\/Beirut\n\* `Asia\/Bishkek` - Asia\/Bishkek\n\* `Asia\/Brunei` - Asia\/Brunei\n\* `Asia\/Calcutta` - Asia\/Calcutta\n\* `Asia\/Chita` - Asia\/Chita\n\* `Asia\/Choibalsan` - Asia\/Choibalsan\n\* `Asia\/Chongqing` - Asia\/Chongqing\n\* `Asia\/Chungking` - Asia\/Chungking\n\* `Asia\/Colombo` - Asia\/Colombo\n\* `Asia\/Dacca` - Asia\/Dacca\n\* `Asia\/Damascus` - Asia\/Damascus\n\* `Asia\/Dhaka` - Asia\/Dhaka\n\* `Asia\/Dili` - Asia\/Dili\n\* `Asia\/Dubai` - Asia\/Dubai\n\* `Asia\/Dushanbe` - Asia\/Dushanbe\n\* `Asia\/Famagusta` - Asia\/Famagusta\n\* `Asia\/Gaza` - Asia\/Gaza\n\* `Asia\/Harbin` - Asia\/Harbin\n\* `Asia\/Hebron` - Asia\/Hebron\n\* `Asia\/Ho_Chi_Minh` - Asia\/Ho_Chi_Minh\n\* `Asia\/Hong_Kong` - Asia\/Hong_Kong\n\* `Asia\/Hovd` - Asia\/Hovd\n\* `Asia\/Irkutsk` - Asia\/Irkutsk\n\* `Asia\/Istanbul` - Asia\/Istanbul\n\* `Asia\/Jakarta` - Asia\/Jakarta\n\* `Asia\/Jayapura` - Asia\/Jayapura\n\* `Asia\/Jerusalem` - Asia\/Jerusalem\n\* `Asia\/Kabul` - Asia\/Kabul\n\* `Asia\/Kamchatka` - Asia\/Kamchatka\n\* `Asia\/Karachi` - Asia\/Karachi\n\* `Asia\/Kashgar` - Asia\/Kashgar\n\* `Asia\/Kathmandu` - Asia\/Kathmandu\n\* `Asia\/Katmandu` - Asia\/Katmandu\n\* `Asia\/Khandyga` - Asia\/Khandyga\n\* `Asia\/Kolkata` - Asia\/Kolkata\n\* `Asia\/Krasnoyarsk` - Asia\/Krasnoyarsk\n\* `Asia\/Kuala_Lumpur` - Asia\/Kuala_Lumpur\n\* `Asia\/Kuching` - Asia\/Kuching\n\* `Asia\/Kuwait` - Asia\/Kuwait\n\* `Asia\/Macao` - Asia\/Macao\n\* `Asia\/Macau` - Asia\/Macau\n\* `Asia\/Magadan` - Asia\/Magadan\n\* `Asia\/Makassar` - Asia\/Makassar\n\* `Asia\/Manila` - Asia\/Manila\n\* `Asia\/Muscat` - Asia\/Muscat\n\* `Asia\/Nicosia` - Asia\/Nicosia\n\* `Asia\/Novokuznetsk` - Asia\/Novokuznetsk\n\* `Asia\/Novosibirsk` - Asia\/Novosibirsk\n\* `Asia\/Omsk` - Asia\/Omsk\n\* `Asia\/Oral` - Asia\/Oral\n\* `Asia\/Phnom_Penh` - Asia\/Phnom_Penh\n\* `Asia\/Pontianak` - Asia\/Pontianak\n\* `Asia\/Pyongyang` - Asia\/Pyongyang\n\* `Asia\/Qatar` - Asia\/Qatar\n\* `Asia\/Qostanay` - Asia\/Qostanay\n\* `Asia\/Qyzylorda` - Asia\/Qyzylorda\n\* `Asia\/Rangoon` - Asia\/Rangoon\n\* `Asia\/Riyadh` - Asia\/Riyadh\n\* `Asia\/Saigon` - Asia\/Saigon\n\* `Asia\/Sakhalin` - Asia\/Sakhalin\n\* `Asia\/Samarkand` - Asia\/Samarkand\n\* `Asia\/Seoul` - Asia\/Seoul\n\* `Asia\/Shanghai` - Asia\/Shanghai\n\* `Asia\/Singapore` - Asia\/Singapore\n\* `Asia\/Srednekolymsk` - Asia\/Srednekolymsk\n\* `Asia\/Taipei` - Asia\/Taipei\n\* `Asia\/Tashkent` - Asia\/Tashkent\n\* `Asia\/Tbilisi` - Asia\/Tbilisi\n\* `Asia\/Tehran` - Asia\/Tehran\n\* `Asia\/Tel_Aviv` - Asia\/Tel_Aviv\n\* `Asia\/Thimbu` - Asia\/Thimbu\n\* `Asia\/Thimphu` - Asia\/Thimphu\n\* `Asia\/Tokyo` - Asia\/Tokyo\n\* `Asia\/Tomsk` - Asia\/Tomsk\n\* `Asia\/Ujung_Pandang` - Asia\/Ujung_Pandang\n\* `Asia\/Ulaanbaatar` - Asia\/Ulaanbaatar\n\* `Asia\/Ulan_Bator` - Asia\/Ulan_Bator\n\* `Asia\/Urumqi` - Asia\/Urumqi\n\* `Asia\/Ust-Nera` - Asia\/Ust-Nera\n\* `Asia\/Vientiane` - Asia\/Vientiane\n\* `Asia\/Vladivostok` - Asia\/Vladivostok\n\* `Asia\/Yakutsk` - Asia\/Yakutsk\n\* `Asia\/Yangon` - Asia\/Yangon\n\* `Asia\/Yekaterinburg` - Asia\/Yekaterinburg\n\* `Asia\/Yerevan` - Asia\/Yerevan\n\* `Atlantic\/Azores` - Atlantic\/Azores\n\* `Atlantic\/Bermuda` - Atlantic\/Bermuda\n\* `Atlantic\/Canary` - Atlantic\/Canary\n\* `Atlantic\/Cape_Verde` - Atlantic\/Cape_Verde\n\* `Atlantic\/Faeroe` - Atlantic\/Faeroe\n\* `Atlantic\/Faroe` - Atlantic\/Faroe\n\* `Atlantic\/Jan_Mayen` - Atlantic\/Jan_Mayen\n\* `Atlantic\/Madeira` - Atlantic\/Madeira\n\* `Atlantic\/Reykjavik` - Atlantic\/Reykjavik\n\* `Atlantic\/South_Georgia` - Atlantic\/South_Georgia\n\* `Atlantic\/St_Helena` - Atlantic\/St_Helena\n\* `Atlantic\/Stanley` - Atlantic\/Stanley\n\* `Australia\/ACT` - Australia\/ACT\n\* `Australia\/Adelaide` - Australia\/Adelaide\n\* `Australia\/Brisbane` - Australia\/Brisbane\n\* `Australia\/Broken_Hill` - Australia\/Broken_Hill\n\* `Australia\/Canberra` - Australia\/Canberra\n\* `Australia\/Currie` - Australia\/Currie\n\* `Australia\/Darwin` - Australia\/Darwin\n\* `Australia\/Eucla` - Australia\/Eucla\n\* `Australia\/Hobart` - Australia\/Hobart\n\* `Australia\/LHI` - Australia\/LHI\n\* `Australia\/Lindeman` - Australia\/Lindeman\n\* `Australia\/Lord_Howe` - Australia\/Lord_Howe\n\* `Australia\/Melbourne` - Australia\/Melbourne\n\* `Australia\/NSW` - Australia\/NSW\n\* `Australia\/North` - Australia\/North\n\* `Australia\/Perth` - Australia\/Perth\n\* `Australia\/Queensland` - Australia\/Queensland\n\* `Australia\/South` - Australia\/South\n\* `Australia\/Sydney` - Australia\/Sydney\n\* `Australia\/Tasmania` - Australia\/Tasmania\n\* `Australia\/Victoria` - Australia\/Victoria\n\* `Australia\/West` - Australia\/West\n\* `Australia\/Yancowinna` - Australia\/Yancowinna\n\* `Brazil\/Acre` - Brazil\/Acre\n\* `Brazil\/DeNoronha` - Brazil\/DeNoronha\n\* `Brazil\/East` - Brazil\/East\n\* `Brazil\/West` - Brazil\/West\n\* `CET` - CET\n\* `CST6CDT` - CST6CDT\n\* `Canada\/Atlantic` - Canada\/Atlantic\n\* `Canada\/Central` - Canada\/Central\n\* `Canada\/Eastern` - Canada\/Eastern\n\* `Canada\/Mountain` - Canada\/Mountain\n\* `Canada\/Newfoundland` - Canada\/Newfoundland\n\* `Canada\/Pacific` - Canada\/Pacific\n\* `Canada\/Saskatchewan` - Canada\/Saskatchewan\n\* `Canada\/Yukon` - Canada\/Yukon\n\* `Chile\/Continental` - Chile\/Continental\n\* `Chile\/EasterIsland` - Chile\/EasterIsland\n\* `Cuba` - Cuba\n\* `EET` - EET\n\* `EST` - EST\n\* `EST5EDT` - EST5EDT\n\* `Egypt` - Egypt\n\* `Eire` - Eire\n\* `Etc\/GMT` - Etc\/GMT\n\* `Etc\/GMT+0` - Etc\/GMT+0\n\* `Etc\/GMT+1` - Etc\/GMT+1\n\* `Etc\/GMT+10` - Etc\/GMT+10\n\* `Etc\/GMT+11` - Etc\/GMT+11\n\* `Etc\/GMT+12` - Etc\/GMT+12\n\* `Etc\/GMT+2` - Etc\/GMT+2\n\* `Etc\/GMT+3` - Etc\/GMT+3\n\* `Etc\/GMT+4` - Etc\/GMT+4\n\* `Etc\/GMT+5` - Etc\/GMT+5\n\* `Etc\/GMT+6` - Etc\/GMT+6\n\* `Etc\/GMT+7` - Etc\/GMT+7\n\* `Etc\/GMT+8` - Etc\/GMT+8\n\* `Etc\/GMT+9` - Etc\/GMT+9\n\* `Etc\/GMT-0` - Etc\/GMT-0\n\* `Etc\/GMT-1` - Etc\/GMT-1\n\* `Etc\/GMT-10` - Etc\/GMT-10\n\* `Etc\/GMT-11` - Etc\/GMT-11\n\* `Etc\/GMT-12` - Etc\/GMT-12\n\* `Etc\/GMT-13` - Etc\/GMT-13\n\* `Etc\/GMT-14` - Etc\/GMT-14\n\* `Etc\/GMT-2` - Etc\/GMT-2\n\* `Etc\/GMT-3` - Etc\/GMT-3\n\* `Etc\/GMT-4` - Etc\/GMT-4\n\* `Etc\/GMT-5` - Etc\/GMT-5\n\* `Etc\/GMT-6` - Etc\/GMT-6\n\* `Etc\/GMT-7` - Etc\/GMT-7\n\* `Etc\/GMT-8` - Etc\/GMT-8\n\* `Etc\/GMT-9` - Etc\/GMT-9\n\* `Etc\/GMT0` - Etc\/GMT0\n\* `Etc\/Greenwich` - Etc\/Greenwich\n\* `Etc\/UCT` - Etc\/UCT\n\* `Etc\/UTC` - Etc\/UTC\n\* `Etc\/Universal` - Etc\/Universal\n\* `Etc\/Zulu` - Etc\/Zulu\n\* `Europe\/Amsterdam` - Europe\/Amsterdam\n\* `Europe\/Andorra` - Europe\/Andorra\n\* `Europe\/Astrakhan` - Europe\/Astrakhan\n\* `Europe\/Athens` - Europe\/Athens\n\* `Europe\/Belfast` - Europe\/Belfast\n\* `Europe\/Belgrade` - Europe\/Belgrade\n\* `Europe\/Berlin` - Europe\/Berlin\n\* `Europe\/Bratislava` - Europe\/Bratislava\n\* `Europe\/Brussels` - Europe\/Brussels\n\* `Europe\/Bucharest` - Europe\/Bucharest\n\* `Europe\/Budapest` - Europe\/Budapest\n\* `Europe\/Busingen` - Europe\/Busingen\n\* `Europe\/Chisinau` - Europe\/Chisinau\n\* `Europe\/Copenhagen` - Europe\/Copenhagen\n\* `Europe\/Dublin` - Europe\/Dublin\n\* `Europe\/Gibraltar` - Europe\/Gibraltar\n\* `Europe\/Guernsey` - Europe\/Guernsey\n\* `Europe\/Helsinki` - Europe\/Helsinki\n\* `Europe\/Isle_of_Man` - Europe\/Isle_of_Man\n\* `Europe\/Istanbul` - Europe\/Istanbul\n\* `Europe\/Jersey` - Europe\/Jersey\n\* `Europe\/Kaliningrad` - Europe\/Kaliningrad\n\* `Europe\/Kiev` - Europe\/Kiev\n\* `Europe\/Kirov` - Europe\/Kirov\n\* `Europe\/Kyiv` - Europe\/Kyiv\n\* `Europe\/Lisbon` - Europe\/Lisbon\n\* `Europe\/Ljubljana` - Europe\/Ljubljana\n\* `Europe\/London` - Europe\/London\n\* `Europe\/Luxembourg` - Europe\/Luxembourg\n\* `Europe\/Madrid` - Europe\/Madrid\n\* `Europe\/Malta` - Europe\/Malta\n\* `Europe\/Mariehamn` - Europe\/Mariehamn\n\* `Europe\/Minsk` - Europe\/Minsk\n\* `Europe\/Monaco` - Europe\/Monaco\n\* `Europe\/Moscow` - Europe\/Moscow\n\* `Europe\/Nicosia` - Europe\/Nicosia\n\* `Europe\/Oslo` - Europe\/Oslo\n\* `Europe\/Paris` - Europe\/Paris\n\* `Europe\/Podgorica` - Europe\/Podgorica\n\* `Europe\/Prague` - Europe\/Prague\n\* `Europe\/Riga` - Europe\/Riga\n\* `Europe\/Rome` - Europe\/Rome\n\* `Europe\/Samara` - Europe\/Samara\n\* `Europe\/San_Marino` - Europe\/San_Marino\n\* `Europe\/Sarajevo` - Europe\/Sarajevo\n\* `Europe\/Saratov` - Europe\/Saratov\n\* `Europe\/Simferopol` - Europe\/Simferopol\n\* `Europe\/Skopje` - Europe\/Skopje\n\* `Europe\/Sofia` - Europe\/Sofia\n\* `Europe\/Stockholm` - Europe\/Stockholm\n\* `Europe\/Tallinn` - Europe\/Tallinn\n\* `Europe\/Tirane` - Europe\/Tirane\n\* `Europe\/Tiraspol` - Europe\/Tiraspol\n\* `Europe\/Ulyanovsk` - Europe\/Ulyanovsk\n\* `Europe\/Uzhgorod` - Europe\/Uzhgorod\n\* `Europe\/Vaduz` - Europe\/Vaduz\n\* `Europe\/Vatican` - Europe\/Vatican\n\* `Europe\/Vienna` - Europe\/Vienna\n\* `Europe\/Vilnius` - Europe\/Vilnius\n\* `Europe\/Volgograd` - Europe\/Volgograd\n\* `Europe\/Warsaw` - Europe\/Warsaw\n\* `Europe\/Zagreb` - Europe\/Zagreb\n\* `Europe\/Zaporozhye` - Europe\/Zaporozhye\n\* `Europe\/Zurich` - Europe\/Zurich\n\* `GB` - GB\n\* `GB-Eire` - GB-Eire\n\* `GMT` - GMT\n\* `GMT+0` - GMT+0\n\* `GMT-0` - GMT-0\n\* `GMT0` - GMT0\n\* `Greenwich` - Greenwich\n\* `HST` - HST\n\* `Hongkong` - Hongkong\n\* `Iceland` - Iceland\n\* `Indian\/Antananarivo` - Indian\/Antananarivo\n\* `Indian\/Chagos` - Indian\/Chagos\n\* `Indian\/Christmas` - Indian\/Christmas\n\* `Indian\/Cocos` - Indian\/Cocos\n\* `Indian\/Comoro` - Indian\/Comoro\n\* `Indian\/Kerguelen` - Indian\/Kerguelen\n\* `Indian\/Mahe` - Indian\/Mahe\n\* `Indian\/Maldives` - Indian\/Maldives\n\* `Indian\/Mauritius` - Indian\/Mauritius\n\* `Indian\/Mayotte` - Indian\/Mayotte\n\* `Indian\/Reunion` - Indian\/Reunion\n\* `Iran` - Iran\n\* `Israel` - Israel\n\* `Jamaica` - Jamaica\n\* `Japan` - Japan\n\* `Kwajalein` - Kwajalein\n\* `Libya` - Libya\n\* `MET` - MET\n\* `MST` - MST\n\* `MST7MDT` - MST7MDT\n\* `Mexico\/BajaNorte` - Mexico\/BajaNorte\n\* `Mexico\/BajaSur` - Mexico\/BajaSur\n\* `Mexico\/General` - Mexico\/General\n\* `NZ` - NZ\n\* `NZ-CHAT` - NZ-CHAT\n\* `Navajo` - Navajo\n\* `PRC` - PRC\n\* `PST8PDT` - PST8PDT\n\* `Pacific\/Apia` - Pacific\/Apia\n\* `Pacific\/Auckland` - Pacific\/Auckland\n\* `Pacific\/Bougainville` - Pacific\/Bougainville\n\* `Pacific\/Chatham` - Pacific\/Chatham\n\* `Pacific\/Chuuk` - Pacific\/Chuuk\n\* `Pacific\/Easter` - Pacific\/Easter\n\* `Pacific\/Efate` - Pacific\/Efate\n\* `Pacific\/Enderbury` - Pacific\/Enderbury\n\* `Pacific\/Fakaofo` - Pacific\/Fakaofo\n\* `Pacific\/Fiji` - Pacific\/Fiji\n\* `Pacific\/Funafuti` - Pacific\/Funafuti\n\* `Pacific\/Galapagos` - Pacific\/Galapagos\n\* `Pacific\/Gambier` - Pacific\/Gambier\n\* `Pacific\/Guadalcanal` - Pacific\/Guadalcanal\n\* `Pacific\/Guam` - Pacific\/Guam\n\* `Pacific\/Honolulu` - Pacific\/Honolulu\n\* `Pacific\/Johnston` - Pacific\/Johnston\n\* `Pacific\/Kanton` - Pacific\/Kanton\n\* `Pacific\/Kiritimati` - Pacific\/Kiritimati\n\* `Pacific\/Kosrae` - Pacific\/Kosrae\n\* `Pacific\/Kwajalein` - Pacific\/Kwajalein\n\* `Pacific\/Majuro` - Pacific\/Majuro\n\* `Pacific\/Marquesas` - Pacific\/Marquesas\n\* `Pacific\/Midway` - Pacific\/Midway\n\* `Pacific\/Nauru` - Pacific\/Nauru\n\* `Pacific\/Niue` - Pacific\/Niue\n\* `Pacific\/Norfolk` - Pacific\/Norfolk\n\* `Pacific\/Noumea` - Pacific\/Noumea\n\* `Pacific\/Pago_Pago` - Pacific\/Pago_Pago\n\* `Pacific\/Palau` - Pacific\/Palau\n\* `Pacific\/Pitcairn` - Pacific\/Pitcairn\n\* `Pacific\/Pohnpei` - Pacific\/Pohnpei\n\* `Pacific\/Ponape` - Pacific\/Ponape\n\* `Pacific\/Port_Moresby` - Pacific\/Port_Moresby\n\* `Pacific\/Rarotonga` - Pacific\/Rarotonga\n\* `Pacific\/Saipan` - Pacific\/Saipan\n\* `Pacific\/Samoa` - Pacific\/Samoa\n\* `Pacific\/Tahiti` - Pacific\/Tahiti\n\* `Pacific\/Tarawa` - Pacific\/Tarawa\n\* `Pacific\/Tongatapu` - Pacific\/Tongatapu\n\* `Pacific\/Truk` - Pacific\/Truk\n\* `Pacific\/Wake` - Pacific\/Wake\n\* `Pacific\/Wallis` - Pacific\/Wallis\n\* `Pacific\/Yap` - Pacific\/Yap\n\* `Poland` - Poland\n\* `Portugal` - Portugal\n\* `ROC` - ROC\n\* `ROK` - ROK\n\* `Singapore` - Singapore\n\* `Turkey` - Turkey\n\* `UCT` - UCT\n\* `US\/Alaska` - US\/Alaska\n\* `US\/Aleutian` - US\/Aleutian\n\* `US\/Arizona` - US\/Arizona\n\* `US\/Central` - US\/Central\n\* `US\/East-Indiana` - US\/East-Indiana\n\* `US\/Eastern` - US\/Eastern\n\* `US\/Hawaii` - US\/Hawaii\n\* `US\/Indiana-Starke` - US\/Indiana-Starke\n\* `US\/Michigan` - US\/Michigan\n\* `US\/Mountain` - US\/Mountain\n\* `US\/Pacific` - US\/Pacific\n\* `US\/Samoa` - US\/Samoa\n\* `UTC` - UTC\n\* `Universal` - Universal\n\* `W-SU` - W-SU\n\* `WET` - WET\n\* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(
                zod
                    .string()
                    .max(
                        organizationsProjectsCompleteProductOnboardingPartialUpdateBodyPersonDisplayNamePropertiesItemMax
                    )
            )
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat(
                'decimal',
                organizationsProjectsCompleteProductOnboardingPartialUpdateBodySessionRecordingSampleRateRegExp
            )
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(
                organizationsProjectsCompleteProductOnboardingPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin
            )
            .max(
                organizationsProjectsCompleteProductOnboardingPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax
            )
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(
                organizationsProjectsCompleteProductOnboardingPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax
            )
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('\* `0` - Sunday\n\* `1` - Monday'),
                zod.null(),
            ])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n\* `0` - Sunday\n\* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsCompleteProductOnboardingPartialUpdateBodyRecordingDomainsItemMax)
                    .nullable()
            )
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations \/ live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(
                        organizationsProjectsCompleteProductOnboardingPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax
                    )
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsCompleteProductOnboardingPartialUpdateBodyDefaultDataThemeMin)
            .max(organizationsProjectsCompleteProductOnboardingPartialUpdateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Manage default evaluation contexts for a project.
 */
export const organizationsProjectsDefaultEvaluationContextsCreateBodyNameMax = 200

export const organizationsProjectsDefaultEvaluationContextsCreateBodyProductDescriptionMax = 1000

export const organizationsProjectsDefaultEvaluationContextsCreateBodyAppUrlsItemMax = 200

export const organizationsProjectsDefaultEvaluationContextsCreateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsDefaultEvaluationContextsCreateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const organizationsProjectsDefaultEvaluationContextsCreateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsDefaultEvaluationContextsCreateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsDefaultEvaluationContextsCreateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsDefaultEvaluationContextsCreateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsDefaultEvaluationContextsCreateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsDefaultEvaluationContextsCreateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsDefaultEvaluationContextsCreateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsDefaultEvaluationContextsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsDefaultEvaluationContextsCreateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsDefaultEvaluationContextsCreateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(zod.string().max(organizationsProjectsDefaultEvaluationContextsCreateBodyAppUrlsItemMax).nullable())
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal\/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal\/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America\/Los_Angeles`).\n\n\* `Africa\/Abidjan` - Africa\/Abidjan\n\* `Africa\/Accra` - Africa\/Accra\n\* `Africa\/Addis_Ababa` - Africa\/Addis_Ababa\n\* `Africa\/Algiers` - Africa\/Algiers\n\* `Africa\/Asmara` - Africa\/Asmara\n\* `Africa\/Asmera` - Africa\/Asmera\n\* `Africa\/Bamako` - Africa\/Bamako\n\* `Africa\/Bangui` - Africa\/Bangui\n\* `Africa\/Banjul` - Africa\/Banjul\n\* `Africa\/Bissau` - Africa\/Bissau\n\* `Africa\/Blantyre` - Africa\/Blantyre\n\* `Africa\/Brazzaville` - Africa\/Brazzaville\n\* `Africa\/Bujumbura` - Africa\/Bujumbura\n\* `Africa\/Cairo` - Africa\/Cairo\n\* `Africa\/Casablanca` - Africa\/Casablanca\n\* `Africa\/Ceuta` - Africa\/Ceuta\n\* `Africa\/Conakry` - Africa\/Conakry\n\* `Africa\/Dakar` - Africa\/Dakar\n\* `Africa\/Dar_es_Salaam` - Africa\/Dar_es_Salaam\n\* `Africa\/Djibouti` - Africa\/Djibouti\n\* `Africa\/Douala` - Africa\/Douala\n\* `Africa\/El_Aaiun` - Africa\/El_Aaiun\n\* `Africa\/Freetown` - Africa\/Freetown\n\* `Africa\/Gaborone` - Africa\/Gaborone\n\* `Africa\/Harare` - Africa\/Harare\n\* `Africa\/Johannesburg` - Africa\/Johannesburg\n\* `Africa\/Juba` - Africa\/Juba\n\* `Africa\/Kampala` - Africa\/Kampala\n\* `Africa\/Khartoum` - Africa\/Khartoum\n\* `Africa\/Kigali` - Africa\/Kigali\n\* `Africa\/Kinshasa` - Africa\/Kinshasa\n\* `Africa\/Lagos` - Africa\/Lagos\n\* `Africa\/Libreville` - Africa\/Libreville\n\* `Africa\/Lome` - Africa\/Lome\n\* `Africa\/Luanda` - Africa\/Luanda\n\* `Africa\/Lubumbashi` - Africa\/Lubumbashi\n\* `Africa\/Lusaka` - Africa\/Lusaka\n\* `Africa\/Malabo` - Africa\/Malabo\n\* `Africa\/Maputo` - Africa\/Maputo\n\* `Africa\/Maseru` - Africa\/Maseru\n\* `Africa\/Mbabane` - Africa\/Mbabane\n\* `Africa\/Mogadishu` - Africa\/Mogadishu\n\* `Africa\/Monrovia` - Africa\/Monrovia\n\* `Africa\/Nairobi` - Africa\/Nairobi\n\* `Africa\/Ndjamena` - Africa\/Ndjamena\n\* `Africa\/Niamey` - Africa\/Niamey\n\* `Africa\/Nouakchott` - Africa\/Nouakchott\n\* `Africa\/Ouagadougou` - Africa\/Ouagadougou\n\* `Africa\/Porto-Novo` - Africa\/Porto-Novo\n\* `Africa\/Sao_Tome` - Africa\/Sao_Tome\n\* `Africa\/Timbuktu` - Africa\/Timbuktu\n\* `Africa\/Tripoli` - Africa\/Tripoli\n\* `Africa\/Tunis` - Africa\/Tunis\n\* `Africa\/Windhoek` - Africa\/Windhoek\n\* `America\/Adak` - America\/Adak\n\* `America\/Anchorage` - America\/Anchorage\n\* `America\/Anguilla` - America\/Anguilla\n\* `America\/Antigua` - America\/Antigua\n\* `America\/Araguaina` - America\/Araguaina\n\* `America\/Argentina\/Buenos_Aires` - America\/Argentina\/Buenos_Aires\n\* `America\/Argentina\/Catamarca` - America\/Argentina\/Catamarca\n\* `America\/Argentina\/ComodRivadavia` - America\/Argentina\/ComodRivadavia\n\* `America\/Argentina\/Cordoba` - America\/Argentina\/Cordoba\n\* `America\/Argentina\/Jujuy` - America\/Argentina\/Jujuy\n\* `America\/Argentina\/La_Rioja` - America\/Argentina\/La_Rioja\n\* `America\/Argentina\/Mendoza` - America\/Argentina\/Mendoza\n\* `America\/Argentina\/Rio_Gallegos` - America\/Argentina\/Rio_Gallegos\n\* `America\/Argentina\/Salta` - America\/Argentina\/Salta\n\* `America\/Argentina\/San_Juan` - America\/Argentina\/San_Juan\n\* `America\/Argentina\/San_Luis` - America\/Argentina\/San_Luis\n\* `America\/Argentina\/Tucuman` - America\/Argentina\/Tucuman\n\* `America\/Argentina\/Ushuaia` - America\/Argentina\/Ushuaia\n\* `America\/Aruba` - America\/Aruba\n\* `America\/Asuncion` - America\/Asuncion\n\* `America\/Atikokan` - America\/Atikokan\n\* `America\/Atka` - America\/Atka\n\* `America\/Bahia` - America\/Bahia\n\* `America\/Bahia_Banderas` - America\/Bahia_Banderas\n\* `America\/Barbados` - America\/Barbados\n\* `America\/Belem` - America\/Belem\n\* `America\/Belize` - America\/Belize\n\* `America\/Blanc-Sablon` - America\/Blanc-Sablon\n\* `America\/Boa_Vista` - America\/Boa_Vista\n\* `America\/Bogota` - America\/Bogota\n\* `America\/Boise` - America\/Boise\n\* `America\/Buenos_Aires` - America\/Buenos_Aires\n\* `America\/Cambridge_Bay` - America\/Cambridge_Bay\n\* `America\/Campo_Grande` - America\/Campo_Grande\n\* `America\/Cancun` - America\/Cancun\n\* `America\/Caracas` - America\/Caracas\n\* `America\/Catamarca` - America\/Catamarca\n\* `America\/Cayenne` - America\/Cayenne\n\* `America\/Cayman` - America\/Cayman\n\* `America\/Chicago` - America\/Chicago\n\* `America\/Chihuahua` - America\/Chihuahua\n\* `America\/Ciudad_Juarez` - America\/Ciudad_Juarez\n\* `America\/Coral_Harbour` - America\/Coral_Harbour\n\* `America\/Cordoba` - America\/Cordoba\n\* `America\/Costa_Rica` - America\/Costa_Rica\n\* `America\/Creston` - America\/Creston\n\* `America\/Cuiaba` - America\/Cuiaba\n\* `America\/Curacao` - America\/Curacao\n\* `America\/Danmarkshavn` - America\/Danmarkshavn\n\* `America\/Dawson` - America\/Dawson\n\* `America\/Dawson_Creek` - America\/Dawson_Creek\n\* `America\/Denver` - America\/Denver\n\* `America\/Detroit` - America\/Detroit\n\* `America\/Dominica` - America\/Dominica\n\* `America\/Edmonton` - America\/Edmonton\n\* `America\/Eirunepe` - America\/Eirunepe\n\* `America\/El_Salvador` - America\/El_Salvador\n\* `America\/Ensenada` - America\/Ensenada\n\* `America\/Fort_Nelson` - America\/Fort_Nelson\n\* `America\/Fort_Wayne` - America\/Fort_Wayne\n\* `America\/Fortaleza` - America\/Fortaleza\n\* `America\/Glace_Bay` - America\/Glace_Bay\n\* `America\/Godthab` - America\/Godthab\n\* `America\/Goose_Bay` - America\/Goose_Bay\n\* `America\/Grand_Turk` - America\/Grand_Turk\n\* `America\/Grenada` - America\/Grenada\n\* `America\/Guadeloupe` - America\/Guadeloupe\n\* `America\/Guatemala` - America\/Guatemala\n\* `America\/Guayaquil` - America\/Guayaquil\n\* `America\/Guyana` - America\/Guyana\n\* `America\/Halifax` - America\/Halifax\n\* `America\/Havana` - America\/Havana\n\* `America\/Hermosillo` - America\/Hermosillo\n\* `America\/Indiana\/Indianapolis` - America\/Indiana\/Indianapolis\n\* `America\/Indiana\/Knox` - America\/Indiana\/Knox\n\* `America\/Indiana\/Marengo` - America\/Indiana\/Marengo\n\* `America\/Indiana\/Petersburg` - America\/Indiana\/Petersburg\n\* `America\/Indiana\/Tell_City` - America\/Indiana\/Tell_City\n\* `America\/Indiana\/Vevay` - America\/Indiana\/Vevay\n\* `America\/Indiana\/Vincennes` - America\/Indiana\/Vincennes\n\* `America\/Indiana\/Winamac` - America\/Indiana\/Winamac\n\* `America\/Indianapolis` - America\/Indianapolis\n\* `America\/Inuvik` - America\/Inuvik\n\* `America\/Iqaluit` - America\/Iqaluit\n\* `America\/Jamaica` - America\/Jamaica\n\* `America\/Jujuy` - America\/Jujuy\n\* `America\/Juneau` - America\/Juneau\n\* `America\/Kentucky\/Louisville` - America\/Kentucky\/Louisville\n\* `America\/Kentucky\/Monticello` - America\/Kentucky\/Monticello\n\* `America\/Knox_IN` - America\/Knox_IN\n\* `America\/Kralendijk` - America\/Kralendijk\n\* `America\/La_Paz` - America\/La_Paz\n\* `America\/Lima` - America\/Lima\n\* `America\/Los_Angeles` - America\/Los_Angeles\n\* `America\/Louisville` - America\/Louisville\n\* `America\/Lower_Princes` - America\/Lower_Princes\n\* `America\/Maceio` - America\/Maceio\n\* `America\/Managua` - America\/Managua\n\* `America\/Manaus` - America\/Manaus\n\* `America\/Marigot` - America\/Marigot\n\* `America\/Martinique` - America\/Martinique\n\* `America\/Matamoros` - America\/Matamoros\n\* `America\/Mazatlan` - America\/Mazatlan\n\* `America\/Mendoza` - America\/Mendoza\n\* `America\/Menominee` - America\/Menominee\n\* `America\/Merida` - America\/Merida\n\* `America\/Metlakatla` - America\/Metlakatla\n\* `America\/Mexico_City` - America\/Mexico_City\n\* `America\/Miquelon` - America\/Miquelon\n\* `America\/Moncton` - America\/Moncton\n\* `America\/Monterrey` - America\/Monterrey\n\* `America\/Montevideo` - America\/Montevideo\n\* `America\/Montreal` - America\/Montreal\n\* `America\/Montserrat` - America\/Montserrat\n\* `America\/Nassau` - America\/Nassau\n\* `America\/New_York` - America\/New_York\n\* `America\/Nipigon` - America\/Nipigon\n\* `America\/Nome` - America\/Nome\n\* `America\/Noronha` - America\/Noronha\n\* `America\/North_Dakota\/Beulah` - America\/North_Dakota\/Beulah\n\* `America\/North_Dakota\/Center` - America\/North_Dakota\/Center\n\* `America\/North_Dakota\/New_Salem` - America\/North_Dakota\/New_Salem\n\* `America\/Nuuk` - America\/Nuuk\n\* `America\/Ojinaga` - America\/Ojinaga\n\* `America\/Panama` - America\/Panama\n\* `America\/Pangnirtung` - America\/Pangnirtung\n\* `America\/Paramaribo` - America\/Paramaribo\n\* `America\/Phoenix` - America\/Phoenix\n\* `America\/Port-au-Prince` - America\/Port-au-Prince\n\* `America\/Port_of_Spain` - America\/Port_of_Spain\n\* `America\/Porto_Acre` - America\/Porto_Acre\n\* `America\/Porto_Velho` - America\/Porto_Velho\n\* `America\/Puerto_Rico` - America\/Puerto_Rico\n\* `America\/Punta_Arenas` - America\/Punta_Arenas\n\* `America\/Rainy_River` - America\/Rainy_River\n\* `America\/Rankin_Inlet` - America\/Rankin_Inlet\n\* `America\/Recife` - America\/Recife\n\* `America\/Regina` - America\/Regina\n\* `America\/Resolute` - America\/Resolute\n\* `America\/Rio_Branco` - America\/Rio_Branco\n\* `America\/Rosario` - America\/Rosario\n\* `America\/Santa_Isabel` - America\/Santa_Isabel\n\* `America\/Santarem` - America\/Santarem\n\* `America\/Santiago` - America\/Santiago\n\* `America\/Santo_Domingo` - America\/Santo_Domingo\n\* `America\/Sao_Paulo` - America\/Sao_Paulo\n\* `America\/Scoresbysund` - America\/Scoresbysund\n\* `America\/Shiprock` - America\/Shiprock\n\* `America\/Sitka` - America\/Sitka\n\* `America\/St_Barthelemy` - America\/St_Barthelemy\n\* `America\/St_Johns` - America\/St_Johns\n\* `America\/St_Kitts` - America\/St_Kitts\n\* `America\/St_Lucia` - America\/St_Lucia\n\* `America\/St_Thomas` - America\/St_Thomas\n\* `America\/St_Vincent` - America\/St_Vincent\n\* `America\/Swift_Current` - America\/Swift_Current\n\* `America\/Tegucigalpa` - America\/Tegucigalpa\n\* `America\/Thule` - America\/Thule\n\* `America\/Thunder_Bay` - America\/Thunder_Bay\n\* `America\/Tijuana` - America\/Tijuana\n\* `America\/Toronto` - America\/Toronto\n\* `America\/Tortola` - America\/Tortola\n\* `America\/Vancouver` - America\/Vancouver\n\* `America\/Virgin` - America\/Virgin\n\* `America\/Whitehorse` - America\/Whitehorse\n\* `America\/Winnipeg` - America\/Winnipeg\n\* `America\/Yakutat` - America\/Yakutat\n\* `America\/Yellowknife` - America\/Yellowknife\n\* `Antarctica\/Casey` - Antarctica\/Casey\n\* `Antarctica\/Davis` - Antarctica\/Davis\n\* `Antarctica\/DumontDUrville` - Antarctica\/DumontDUrville\n\* `Antarctica\/Macquarie` - Antarctica\/Macquarie\n\* `Antarctica\/Mawson` - Antarctica\/Mawson\n\* `Antarctica\/McMurdo` - Antarctica\/McMurdo\n\* `Antarctica\/Palmer` - Antarctica\/Palmer\n\* `Antarctica\/Rothera` - Antarctica\/Rothera\n\* `Antarctica\/South_Pole` - Antarctica\/South_Pole\n\* `Antarctica\/Syowa` - Antarctica\/Syowa\n\* `Antarctica\/Troll` - Antarctica\/Troll\n\* `Antarctica\/Vostok` - Antarctica\/Vostok\n\* `Arctic\/Longyearbyen` - Arctic\/Longyearbyen\n\* `Asia\/Aden` - Asia\/Aden\n\* `Asia\/Almaty` - Asia\/Almaty\n\* `Asia\/Amman` - Asia\/Amman\n\* `Asia\/Anadyr` - Asia\/Anadyr\n\* `Asia\/Aqtau` - Asia\/Aqtau\n\* `Asia\/Aqtobe` - Asia\/Aqtobe\n\* `Asia\/Ashgabat` - Asia\/Ashgabat\n\* `Asia\/Ashkhabad` - Asia\/Ashkhabad\n\* `Asia\/Atyrau` - Asia\/Atyrau\n\* `Asia\/Baghdad` - Asia\/Baghdad\n\* `Asia\/Bahrain` - Asia\/Bahrain\n\* `Asia\/Baku` - Asia\/Baku\n\* `Asia\/Bangkok` - Asia\/Bangkok\n\* `Asia\/Barnaul` - Asia\/Barnaul\n\* `Asia\/Beirut` - Asia\/Beirut\n\* `Asia\/Bishkek` - Asia\/Bishkek\n\* `Asia\/Brunei` - Asia\/Brunei\n\* `Asia\/Calcutta` - Asia\/Calcutta\n\* `Asia\/Chita` - Asia\/Chita\n\* `Asia\/Choibalsan` - Asia\/Choibalsan\n\* `Asia\/Chongqing` - Asia\/Chongqing\n\* `Asia\/Chungking` - Asia\/Chungking\n\* `Asia\/Colombo` - Asia\/Colombo\n\* `Asia\/Dacca` - Asia\/Dacca\n\* `Asia\/Damascus` - Asia\/Damascus\n\* `Asia\/Dhaka` - Asia\/Dhaka\n\* `Asia\/Dili` - Asia\/Dili\n\* `Asia\/Dubai` - Asia\/Dubai\n\* `Asia\/Dushanbe` - Asia\/Dushanbe\n\* `Asia\/Famagusta` - Asia\/Famagusta\n\* `Asia\/Gaza` - Asia\/Gaza\n\* `Asia\/Harbin` - Asia\/Harbin\n\* `Asia\/Hebron` - Asia\/Hebron\n\* `Asia\/Ho_Chi_Minh` - Asia\/Ho_Chi_Minh\n\* `Asia\/Hong_Kong` - Asia\/Hong_Kong\n\* `Asia\/Hovd` - Asia\/Hovd\n\* `Asia\/Irkutsk` - Asia\/Irkutsk\n\* `Asia\/Istanbul` - Asia\/Istanbul\n\* `Asia\/Jakarta` - Asia\/Jakarta\n\* `Asia\/Jayapura` - Asia\/Jayapura\n\* `Asia\/Jerusalem` - Asia\/Jerusalem\n\* `Asia\/Kabul` - Asia\/Kabul\n\* `Asia\/Kamchatka` - Asia\/Kamchatka\n\* `Asia\/Karachi` - Asia\/Karachi\n\* `Asia\/Kashgar` - Asia\/Kashgar\n\* `Asia\/Kathmandu` - Asia\/Kathmandu\n\* `Asia\/Katmandu` - Asia\/Katmandu\n\* `Asia\/Khandyga` - Asia\/Khandyga\n\* `Asia\/Kolkata` - Asia\/Kolkata\n\* `Asia\/Krasnoyarsk` - Asia\/Krasnoyarsk\n\* `Asia\/Kuala_Lumpur` - Asia\/Kuala_Lumpur\n\* `Asia\/Kuching` - Asia\/Kuching\n\* `Asia\/Kuwait` - Asia\/Kuwait\n\* `Asia\/Macao` - Asia\/Macao\n\* `Asia\/Macau` - Asia\/Macau\n\* `Asia\/Magadan` - Asia\/Magadan\n\* `Asia\/Makassar` - Asia\/Makassar\n\* `Asia\/Manila` - Asia\/Manila\n\* `Asia\/Muscat` - Asia\/Muscat\n\* `Asia\/Nicosia` - Asia\/Nicosia\n\* `Asia\/Novokuznetsk` - Asia\/Novokuznetsk\n\* `Asia\/Novosibirsk` - Asia\/Novosibirsk\n\* `Asia\/Omsk` - Asia\/Omsk\n\* `Asia\/Oral` - Asia\/Oral\n\* `Asia\/Phnom_Penh` - Asia\/Phnom_Penh\n\* `Asia\/Pontianak` - Asia\/Pontianak\n\* `Asia\/Pyongyang` - Asia\/Pyongyang\n\* `Asia\/Qatar` - Asia\/Qatar\n\* `Asia\/Qostanay` - Asia\/Qostanay\n\* `Asia\/Qyzylorda` - Asia\/Qyzylorda\n\* `Asia\/Rangoon` - Asia\/Rangoon\n\* `Asia\/Riyadh` - Asia\/Riyadh\n\* `Asia\/Saigon` - Asia\/Saigon\n\* `Asia\/Sakhalin` - Asia\/Sakhalin\n\* `Asia\/Samarkand` - Asia\/Samarkand\n\* `Asia\/Seoul` - Asia\/Seoul\n\* `Asia\/Shanghai` - Asia\/Shanghai\n\* `Asia\/Singapore` - Asia\/Singapore\n\* `Asia\/Srednekolymsk` - Asia\/Srednekolymsk\n\* `Asia\/Taipei` - Asia\/Taipei\n\* `Asia\/Tashkent` - Asia\/Tashkent\n\* `Asia\/Tbilisi` - Asia\/Tbilisi\n\* `Asia\/Tehran` - Asia\/Tehran\n\* `Asia\/Tel_Aviv` - Asia\/Tel_Aviv\n\* `Asia\/Thimbu` - Asia\/Thimbu\n\* `Asia\/Thimphu` - Asia\/Thimphu\n\* `Asia\/Tokyo` - Asia\/Tokyo\n\* `Asia\/Tomsk` - Asia\/Tomsk\n\* `Asia\/Ujung_Pandang` - Asia\/Ujung_Pandang\n\* `Asia\/Ulaanbaatar` - Asia\/Ulaanbaatar\n\* `Asia\/Ulan_Bator` - Asia\/Ulan_Bator\n\* `Asia\/Urumqi` - Asia\/Urumqi\n\* `Asia\/Ust-Nera` - Asia\/Ust-Nera\n\* `Asia\/Vientiane` - Asia\/Vientiane\n\* `Asia\/Vladivostok` - Asia\/Vladivostok\n\* `Asia\/Yakutsk` - Asia\/Yakutsk\n\* `Asia\/Yangon` - Asia\/Yangon\n\* `Asia\/Yekaterinburg` - Asia\/Yekaterinburg\n\* `Asia\/Yerevan` - Asia\/Yerevan\n\* `Atlantic\/Azores` - Atlantic\/Azores\n\* `Atlantic\/Bermuda` - Atlantic\/Bermuda\n\* `Atlantic\/Canary` - Atlantic\/Canary\n\* `Atlantic\/Cape_Verde` - Atlantic\/Cape_Verde\n\* `Atlantic\/Faeroe` - Atlantic\/Faeroe\n\* `Atlantic\/Faroe` - Atlantic\/Faroe\n\* `Atlantic\/Jan_Mayen` - Atlantic\/Jan_Mayen\n\* `Atlantic\/Madeira` - Atlantic\/Madeira\n\* `Atlantic\/Reykjavik` - Atlantic\/Reykjavik\n\* `Atlantic\/South_Georgia` - Atlantic\/South_Georgia\n\* `Atlantic\/St_Helena` - Atlantic\/St_Helena\n\* `Atlantic\/Stanley` - Atlantic\/Stanley\n\* `Australia\/ACT` - Australia\/ACT\n\* `Australia\/Adelaide` - Australia\/Adelaide\n\* `Australia\/Brisbane` - Australia\/Brisbane\n\* `Australia\/Broken_Hill` - Australia\/Broken_Hill\n\* `Australia\/Canberra` - Australia\/Canberra\n\* `Australia\/Currie` - Australia\/Currie\n\* `Australia\/Darwin` - Australia\/Darwin\n\* `Australia\/Eucla` - Australia\/Eucla\n\* `Australia\/Hobart` - Australia\/Hobart\n\* `Australia\/LHI` - Australia\/LHI\n\* `Australia\/Lindeman` - Australia\/Lindeman\n\* `Australia\/Lord_Howe` - Australia\/Lord_Howe\n\* `Australia\/Melbourne` - Australia\/Melbourne\n\* `Australia\/NSW` - Australia\/NSW\n\* `Australia\/North` - Australia\/North\n\* `Australia\/Perth` - Australia\/Perth\n\* `Australia\/Queensland` - Australia\/Queensland\n\* `Australia\/South` - Australia\/South\n\* `Australia\/Sydney` - Australia\/Sydney\n\* `Australia\/Tasmania` - Australia\/Tasmania\n\* `Australia\/Victoria` - Australia\/Victoria\n\* `Australia\/West` - Australia\/West\n\* `Australia\/Yancowinna` - Australia\/Yancowinna\n\* `Brazil\/Acre` - Brazil\/Acre\n\* `Brazil\/DeNoronha` - Brazil\/DeNoronha\n\* `Brazil\/East` - Brazil\/East\n\* `Brazil\/West` - Brazil\/West\n\* `CET` - CET\n\* `CST6CDT` - CST6CDT\n\* `Canada\/Atlantic` - Canada\/Atlantic\n\* `Canada\/Central` - Canada\/Central\n\* `Canada\/Eastern` - Canada\/Eastern\n\* `Canada\/Mountain` - Canada\/Mountain\n\* `Canada\/Newfoundland` - Canada\/Newfoundland\n\* `Canada\/Pacific` - Canada\/Pacific\n\* `Canada\/Saskatchewan` - Canada\/Saskatchewan\n\* `Canada\/Yukon` - Canada\/Yukon\n\* `Chile\/Continental` - Chile\/Continental\n\* `Chile\/EasterIsland` - Chile\/EasterIsland\n\* `Cuba` - Cuba\n\* `EET` - EET\n\* `EST` - EST\n\* `EST5EDT` - EST5EDT\n\* `Egypt` - Egypt\n\* `Eire` - Eire\n\* `Etc\/GMT` - Etc\/GMT\n\* `Etc\/GMT+0` - Etc\/GMT+0\n\* `Etc\/GMT+1` - Etc\/GMT+1\n\* `Etc\/GMT+10` - Etc\/GMT+10\n\* `Etc\/GMT+11` - Etc\/GMT+11\n\* `Etc\/GMT+12` - Etc\/GMT+12\n\* `Etc\/GMT+2` - Etc\/GMT+2\n\* `Etc\/GMT+3` - Etc\/GMT+3\n\* `Etc\/GMT+4` - Etc\/GMT+4\n\* `Etc\/GMT+5` - Etc\/GMT+5\n\* `Etc\/GMT+6` - Etc\/GMT+6\n\* `Etc\/GMT+7` - Etc\/GMT+7\n\* `Etc\/GMT+8` - Etc\/GMT+8\n\* `Etc\/GMT+9` - Etc\/GMT+9\n\* `Etc\/GMT-0` - Etc\/GMT-0\n\* `Etc\/GMT-1` - Etc\/GMT-1\n\* `Etc\/GMT-10` - Etc\/GMT-10\n\* `Etc\/GMT-11` - Etc\/GMT-11\n\* `Etc\/GMT-12` - Etc\/GMT-12\n\* `Etc\/GMT-13` - Etc\/GMT-13\n\* `Etc\/GMT-14` - Etc\/GMT-14\n\* `Etc\/GMT-2` - Etc\/GMT-2\n\* `Etc\/GMT-3` - Etc\/GMT-3\n\* `Etc\/GMT-4` - Etc\/GMT-4\n\* `Etc\/GMT-5` - Etc\/GMT-5\n\* `Etc\/GMT-6` - Etc\/GMT-6\n\* `Etc\/GMT-7` - Etc\/GMT-7\n\* `Etc\/GMT-8` - Etc\/GMT-8\n\* `Etc\/GMT-9` - Etc\/GMT-9\n\* `Etc\/GMT0` - Etc\/GMT0\n\* `Etc\/Greenwich` - Etc\/Greenwich\n\* `Etc\/UCT` - Etc\/UCT\n\* `Etc\/UTC` - Etc\/UTC\n\* `Etc\/Universal` - Etc\/Universal\n\* `Etc\/Zulu` - Etc\/Zulu\n\* `Europe\/Amsterdam` - Europe\/Amsterdam\n\* `Europe\/Andorra` - Europe\/Andorra\n\* `Europe\/Astrakhan` - Europe\/Astrakhan\n\* `Europe\/Athens` - Europe\/Athens\n\* `Europe\/Belfast` - Europe\/Belfast\n\* `Europe\/Belgrade` - Europe\/Belgrade\n\* `Europe\/Berlin` - Europe\/Berlin\n\* `Europe\/Bratislava` - Europe\/Bratislava\n\* `Europe\/Brussels` - Europe\/Brussels\n\* `Europe\/Bucharest` - Europe\/Bucharest\n\* `Europe\/Budapest` - Europe\/Budapest\n\* `Europe\/Busingen` - Europe\/Busingen\n\* `Europe\/Chisinau` - Europe\/Chisinau\n\* `Europe\/Copenhagen` - Europe\/Copenhagen\n\* `Europe\/Dublin` - Europe\/Dublin\n\* `Europe\/Gibraltar` - Europe\/Gibraltar\n\* `Europe\/Guernsey` - Europe\/Guernsey\n\* `Europe\/Helsinki` - Europe\/Helsinki\n\* `Europe\/Isle_of_Man` - Europe\/Isle_of_Man\n\* `Europe\/Istanbul` - Europe\/Istanbul\n\* `Europe\/Jersey` - Europe\/Jersey\n\* `Europe\/Kaliningrad` - Europe\/Kaliningrad\n\* `Europe\/Kiev` - Europe\/Kiev\n\* `Europe\/Kirov` - Europe\/Kirov\n\* `Europe\/Kyiv` - Europe\/Kyiv\n\* `Europe\/Lisbon` - Europe\/Lisbon\n\* `Europe\/Ljubljana` - Europe\/Ljubljana\n\* `Europe\/London` - Europe\/London\n\* `Europe\/Luxembourg` - Europe\/Luxembourg\n\* `Europe\/Madrid` - Europe\/Madrid\n\* `Europe\/Malta` - Europe\/Malta\n\* `Europe\/Mariehamn` - Europe\/Mariehamn\n\* `Europe\/Minsk` - Europe\/Minsk\n\* `Europe\/Monaco` - Europe\/Monaco\n\* `Europe\/Moscow` - Europe\/Moscow\n\* `Europe\/Nicosia` - Europe\/Nicosia\n\* `Europe\/Oslo` - Europe\/Oslo\n\* `Europe\/Paris` - Europe\/Paris\n\* `Europe\/Podgorica` - Europe\/Podgorica\n\* `Europe\/Prague` - Europe\/Prague\n\* `Europe\/Riga` - Europe\/Riga\n\* `Europe\/Rome` - Europe\/Rome\n\* `Europe\/Samara` - Europe\/Samara\n\* `Europe\/San_Marino` - Europe\/San_Marino\n\* `Europe\/Sarajevo` - Europe\/Sarajevo\n\* `Europe\/Saratov` - Europe\/Saratov\n\* `Europe\/Simferopol` - Europe\/Simferopol\n\* `Europe\/Skopje` - Europe\/Skopje\n\* `Europe\/Sofia` - Europe\/Sofia\n\* `Europe\/Stockholm` - Europe\/Stockholm\n\* `Europe\/Tallinn` - Europe\/Tallinn\n\* `Europe\/Tirane` - Europe\/Tirane\n\* `Europe\/Tiraspol` - Europe\/Tiraspol\n\* `Europe\/Ulyanovsk` - Europe\/Ulyanovsk\n\* `Europe\/Uzhgorod` - Europe\/Uzhgorod\n\* `Europe\/Vaduz` - Europe\/Vaduz\n\* `Europe\/Vatican` - Europe\/Vatican\n\* `Europe\/Vienna` - Europe\/Vienna\n\* `Europe\/Vilnius` - Europe\/Vilnius\n\* `Europe\/Volgograd` - Europe\/Volgograd\n\* `Europe\/Warsaw` - Europe\/Warsaw\n\* `Europe\/Zagreb` - Europe\/Zagreb\n\* `Europe\/Zaporozhye` - Europe\/Zaporozhye\n\* `Europe\/Zurich` - Europe\/Zurich\n\* `GB` - GB\n\* `GB-Eire` - GB-Eire\n\* `GMT` - GMT\n\* `GMT+0` - GMT+0\n\* `GMT-0` - GMT-0\n\* `GMT0` - GMT0\n\* `Greenwich` - Greenwich\n\* `HST` - HST\n\* `Hongkong` - Hongkong\n\* `Iceland` - Iceland\n\* `Indian\/Antananarivo` - Indian\/Antananarivo\n\* `Indian\/Chagos` - Indian\/Chagos\n\* `Indian\/Christmas` - Indian\/Christmas\n\* `Indian\/Cocos` - Indian\/Cocos\n\* `Indian\/Comoro` - Indian\/Comoro\n\* `Indian\/Kerguelen` - Indian\/Kerguelen\n\* `Indian\/Mahe` - Indian\/Mahe\n\* `Indian\/Maldives` - Indian\/Maldives\n\* `Indian\/Mauritius` - Indian\/Mauritius\n\* `Indian\/Mayotte` - Indian\/Mayotte\n\* `Indian\/Reunion` - Indian\/Reunion\n\* `Iran` - Iran\n\* `Israel` - Israel\n\* `Jamaica` - Jamaica\n\* `Japan` - Japan\n\* `Kwajalein` - Kwajalein\n\* `Libya` - Libya\n\* `MET` - MET\n\* `MST` - MST\n\* `MST7MDT` - MST7MDT\n\* `Mexico\/BajaNorte` - Mexico\/BajaNorte\n\* `Mexico\/BajaSur` - Mexico\/BajaSur\n\* `Mexico\/General` - Mexico\/General\n\* `NZ` - NZ\n\* `NZ-CHAT` - NZ-CHAT\n\* `Navajo` - Navajo\n\* `PRC` - PRC\n\* `PST8PDT` - PST8PDT\n\* `Pacific\/Apia` - Pacific\/Apia\n\* `Pacific\/Auckland` - Pacific\/Auckland\n\* `Pacific\/Bougainville` - Pacific\/Bougainville\n\* `Pacific\/Chatham` - Pacific\/Chatham\n\* `Pacific\/Chuuk` - Pacific\/Chuuk\n\* `Pacific\/Easter` - Pacific\/Easter\n\* `Pacific\/Efate` - Pacific\/Efate\n\* `Pacific\/Enderbury` - Pacific\/Enderbury\n\* `Pacific\/Fakaofo` - Pacific\/Fakaofo\n\* `Pacific\/Fiji` - Pacific\/Fiji\n\* `Pacific\/Funafuti` - Pacific\/Funafuti\n\* `Pacific\/Galapagos` - Pacific\/Galapagos\n\* `Pacific\/Gambier` - Pacific\/Gambier\n\* `Pacific\/Guadalcanal` - Pacific\/Guadalcanal\n\* `Pacific\/Guam` - Pacific\/Guam\n\* `Pacific\/Honolulu` - Pacific\/Honolulu\n\* `Pacific\/Johnston` - Pacific\/Johnston\n\* `Pacific\/Kanton` - Pacific\/Kanton\n\* `Pacific\/Kiritimati` - Pacific\/Kiritimati\n\* `Pacific\/Kosrae` - Pacific\/Kosrae\n\* `Pacific\/Kwajalein` - Pacific\/Kwajalein\n\* `Pacific\/Majuro` - Pacific\/Majuro\n\* `Pacific\/Marquesas` - Pacific\/Marquesas\n\* `Pacific\/Midway` - Pacific\/Midway\n\* `Pacific\/Nauru` - Pacific\/Nauru\n\* `Pacific\/Niue` - Pacific\/Niue\n\* `Pacific\/Norfolk` - Pacific\/Norfolk\n\* `Pacific\/Noumea` - Pacific\/Noumea\n\* `Pacific\/Pago_Pago` - Pacific\/Pago_Pago\n\* `Pacific\/Palau` - Pacific\/Palau\n\* `Pacific\/Pitcairn` - Pacific\/Pitcairn\n\* `Pacific\/Pohnpei` - Pacific\/Pohnpei\n\* `Pacific\/Ponape` - Pacific\/Ponape\n\* `Pacific\/Port_Moresby` - Pacific\/Port_Moresby\n\* `Pacific\/Rarotonga` - Pacific\/Rarotonga\n\* `Pacific\/Saipan` - Pacific\/Saipan\n\* `Pacific\/Samoa` - Pacific\/Samoa\n\* `Pacific\/Tahiti` - Pacific\/Tahiti\n\* `Pacific\/Tarawa` - Pacific\/Tarawa\n\* `Pacific\/Tongatapu` - Pacific\/Tongatapu\n\* `Pacific\/Truk` - Pacific\/Truk\n\* `Pacific\/Wake` - Pacific\/Wake\n\* `Pacific\/Wallis` - Pacific\/Wallis\n\* `Pacific\/Yap` - Pacific\/Yap\n\* `Poland` - Poland\n\* `Portugal` - Portugal\n\* `ROC` - ROC\n\* `ROK` - ROK\n\* `Singapore` - Singapore\n\* `Turkey` - Turkey\n\* `UCT` - UCT\n\* `US\/Alaska` - US\/Alaska\n\* `US\/Aleutian` - US\/Aleutian\n\* `US\/Arizona` - US\/Arizona\n\* `US\/Central` - US\/Central\n\* `US\/East-Indiana` - US\/East-Indiana\n\* `US\/Eastern` - US\/Eastern\n\* `US\/Hawaii` - US\/Hawaii\n\* `US\/Indiana-Starke` - US\/Indiana-Starke\n\* `US\/Michigan` - US\/Michigan\n\* `US\/Mountain` - US\/Mountain\n\* `US\/Pacific` - US\/Pacific\n\* `US\/Samoa` - US\/Samoa\n\* `UTC` - UTC\n\* `Universal` - Universal\n\* `W-SU` - W-SU\n\* `WET` - WET\n\* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsDefaultEvaluationContextsCreateBodyPersonDisplayNamePropertiesItemMax)
            )
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat(
                'decimal',
                organizationsProjectsDefaultEvaluationContextsCreateBodySessionRecordingSampleRateRegExp
            )
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(organizationsProjectsDefaultEvaluationContextsCreateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(organizationsProjectsDefaultEvaluationContextsCreateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(organizationsProjectsDefaultEvaluationContextsCreateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('\* `0` - Sunday\n\* `1` - Monday'),
                zod.null(),
            ])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n\* `0` - Sunday\n\* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsDefaultEvaluationContextsCreateBodyRecordingDomainsItemMax)
                    .nullable()
            )
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations \/ live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(
                        organizationsProjectsDefaultEvaluationContextsCreateBodyMarketingAnalyticsConfigAttributionWindowDaysMax
                    )
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsDefaultEvaluationContextsCreateBodyDefaultDataThemeMin)
            .max(organizationsProjectsDefaultEvaluationContextsCreateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Manage default release conditions for new feature flags in this project.
 */
export const organizationsProjectsDefaultReleaseConditionsUpdateBodyNameMax = 200

export const organizationsProjectsDefaultReleaseConditionsUpdateBodyProductDescriptionMax = 1000

export const organizationsProjectsDefaultReleaseConditionsUpdateBodyAppUrlsItemMax = 200

export const organizationsProjectsDefaultReleaseConditionsUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsDefaultReleaseConditionsUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const organizationsProjectsDefaultReleaseConditionsUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsDefaultReleaseConditionsUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsDefaultReleaseConditionsUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsDefaultReleaseConditionsUpdateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsDefaultReleaseConditionsUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsDefaultReleaseConditionsUpdateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsDefaultReleaseConditionsUpdateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsDefaultReleaseConditionsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsDefaultReleaseConditionsUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsDefaultReleaseConditionsUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(zod.string().max(organizationsProjectsDefaultReleaseConditionsUpdateBodyAppUrlsItemMax).nullable())
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal\/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal\/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America\/Los_Angeles`).\n\n\* `Africa\/Abidjan` - Africa\/Abidjan\n\* `Africa\/Accra` - Africa\/Accra\n\* `Africa\/Addis_Ababa` - Africa\/Addis_Ababa\n\* `Africa\/Algiers` - Africa\/Algiers\n\* `Africa\/Asmara` - Africa\/Asmara\n\* `Africa\/Asmera` - Africa\/Asmera\n\* `Africa\/Bamako` - Africa\/Bamako\n\* `Africa\/Bangui` - Africa\/Bangui\n\* `Africa\/Banjul` - Africa\/Banjul\n\* `Africa\/Bissau` - Africa\/Bissau\n\* `Africa\/Blantyre` - Africa\/Blantyre\n\* `Africa\/Brazzaville` - Africa\/Brazzaville\n\* `Africa\/Bujumbura` - Africa\/Bujumbura\n\* `Africa\/Cairo` - Africa\/Cairo\n\* `Africa\/Casablanca` - Africa\/Casablanca\n\* `Africa\/Ceuta` - Africa\/Ceuta\n\* `Africa\/Conakry` - Africa\/Conakry\n\* `Africa\/Dakar` - Africa\/Dakar\n\* `Africa\/Dar_es_Salaam` - Africa\/Dar_es_Salaam\n\* `Africa\/Djibouti` - Africa\/Djibouti\n\* `Africa\/Douala` - Africa\/Douala\n\* `Africa\/El_Aaiun` - Africa\/El_Aaiun\n\* `Africa\/Freetown` - Africa\/Freetown\n\* `Africa\/Gaborone` - Africa\/Gaborone\n\* `Africa\/Harare` - Africa\/Harare\n\* `Africa\/Johannesburg` - Africa\/Johannesburg\n\* `Africa\/Juba` - Africa\/Juba\n\* `Africa\/Kampala` - Africa\/Kampala\n\* `Africa\/Khartoum` - Africa\/Khartoum\n\* `Africa\/Kigali` - Africa\/Kigali\n\* `Africa\/Kinshasa` - Africa\/Kinshasa\n\* `Africa\/Lagos` - Africa\/Lagos\n\* `Africa\/Libreville` - Africa\/Libreville\n\* `Africa\/Lome` - Africa\/Lome\n\* `Africa\/Luanda` - Africa\/Luanda\n\* `Africa\/Lubumbashi` - Africa\/Lubumbashi\n\* `Africa\/Lusaka` - Africa\/Lusaka\n\* `Africa\/Malabo` - Africa\/Malabo\n\* `Africa\/Maputo` - Africa\/Maputo\n\* `Africa\/Maseru` - Africa\/Maseru\n\* `Africa\/Mbabane` - Africa\/Mbabane\n\* `Africa\/Mogadishu` - Africa\/Mogadishu\n\* `Africa\/Monrovia` - Africa\/Monrovia\n\* `Africa\/Nairobi` - Africa\/Nairobi\n\* `Africa\/Ndjamena` - Africa\/Ndjamena\n\* `Africa\/Niamey` - Africa\/Niamey\n\* `Africa\/Nouakchott` - Africa\/Nouakchott\n\* `Africa\/Ouagadougou` - Africa\/Ouagadougou\n\* `Africa\/Porto-Novo` - Africa\/Porto-Novo\n\* `Africa\/Sao_Tome` - Africa\/Sao_Tome\n\* `Africa\/Timbuktu` - Africa\/Timbuktu\n\* `Africa\/Tripoli` - Africa\/Tripoli\n\* `Africa\/Tunis` - Africa\/Tunis\n\* `Africa\/Windhoek` - Africa\/Windhoek\n\* `America\/Adak` - America\/Adak\n\* `America\/Anchorage` - America\/Anchorage\n\* `America\/Anguilla` - America\/Anguilla\n\* `America\/Antigua` - America\/Antigua\n\* `America\/Araguaina` - America\/Araguaina\n\* `America\/Argentina\/Buenos_Aires` - America\/Argentina\/Buenos_Aires\n\* `America\/Argentina\/Catamarca` - America\/Argentina\/Catamarca\n\* `America\/Argentina\/ComodRivadavia` - America\/Argentina\/ComodRivadavia\n\* `America\/Argentina\/Cordoba` - America\/Argentina\/Cordoba\n\* `America\/Argentina\/Jujuy` - America\/Argentina\/Jujuy\n\* `America\/Argentina\/La_Rioja` - America\/Argentina\/La_Rioja\n\* `America\/Argentina\/Mendoza` - America\/Argentina\/Mendoza\n\* `America\/Argentina\/Rio_Gallegos` - America\/Argentina\/Rio_Gallegos\n\* `America\/Argentina\/Salta` - America\/Argentina\/Salta\n\* `America\/Argentina\/San_Juan` - America\/Argentina\/San_Juan\n\* `America\/Argentina\/San_Luis` - America\/Argentina\/San_Luis\n\* `America\/Argentina\/Tucuman` - America\/Argentina\/Tucuman\n\* `America\/Argentina\/Ushuaia` - America\/Argentina\/Ushuaia\n\* `America\/Aruba` - America\/Aruba\n\* `America\/Asuncion` - America\/Asuncion\n\* `America\/Atikokan` - America\/Atikokan\n\* `America\/Atka` - America\/Atka\n\* `America\/Bahia` - America\/Bahia\n\* `America\/Bahia_Banderas` - America\/Bahia_Banderas\n\* `America\/Barbados` - America\/Barbados\n\* `America\/Belem` - America\/Belem\n\* `America\/Belize` - America\/Belize\n\* `America\/Blanc-Sablon` - America\/Blanc-Sablon\n\* `America\/Boa_Vista` - America\/Boa_Vista\n\* `America\/Bogota` - America\/Bogota\n\* `America\/Boise` - America\/Boise\n\* `America\/Buenos_Aires` - America\/Buenos_Aires\n\* `America\/Cambridge_Bay` - America\/Cambridge_Bay\n\* `America\/Campo_Grande` - America\/Campo_Grande\n\* `America\/Cancun` - America\/Cancun\n\* `America\/Caracas` - America\/Caracas\n\* `America\/Catamarca` - America\/Catamarca\n\* `America\/Cayenne` - America\/Cayenne\n\* `America\/Cayman` - America\/Cayman\n\* `America\/Chicago` - America\/Chicago\n\* `America\/Chihuahua` - America\/Chihuahua\n\* `America\/Ciudad_Juarez` - America\/Ciudad_Juarez\n\* `America\/Coral_Harbour` - America\/Coral_Harbour\n\* `America\/Cordoba` - America\/Cordoba\n\* `America\/Costa_Rica` - America\/Costa_Rica\n\* `America\/Creston` - America\/Creston\n\* `America\/Cuiaba` - America\/Cuiaba\n\* `America\/Curacao` - America\/Curacao\n\* `America\/Danmarkshavn` - America\/Danmarkshavn\n\* `America\/Dawson` - America\/Dawson\n\* `America\/Dawson_Creek` - America\/Dawson_Creek\n\* `America\/Denver` - America\/Denver\n\* `America\/Detroit` - America\/Detroit\n\* `America\/Dominica` - America\/Dominica\n\* `America\/Edmonton` - America\/Edmonton\n\* `America\/Eirunepe` - America\/Eirunepe\n\* `America\/El_Salvador` - America\/El_Salvador\n\* `America\/Ensenada` - America\/Ensenada\n\* `America\/Fort_Nelson` - America\/Fort_Nelson\n\* `America\/Fort_Wayne` - America\/Fort_Wayne\n\* `America\/Fortaleza` - America\/Fortaleza\n\* `America\/Glace_Bay` - America\/Glace_Bay\n\* `America\/Godthab` - America\/Godthab\n\* `America\/Goose_Bay` - America\/Goose_Bay\n\* `America\/Grand_Turk` - America\/Grand_Turk\n\* `America\/Grenada` - America\/Grenada\n\* `America\/Guadeloupe` - America\/Guadeloupe\n\* `America\/Guatemala` - America\/Guatemala\n\* `America\/Guayaquil` - America\/Guayaquil\n\* `America\/Guyana` - America\/Guyana\n\* `America\/Halifax` - America\/Halifax\n\* `America\/Havana` - America\/Havana\n\* `America\/Hermosillo` - America\/Hermosillo\n\* `America\/Indiana\/Indianapolis` - America\/Indiana\/Indianapolis\n\* `America\/Indiana\/Knox` - America\/Indiana\/Knox\n\* `America\/Indiana\/Marengo` - America\/Indiana\/Marengo\n\* `America\/Indiana\/Petersburg` - America\/Indiana\/Petersburg\n\* `America\/Indiana\/Tell_City` - America\/Indiana\/Tell_City\n\* `America\/Indiana\/Vevay` - America\/Indiana\/Vevay\n\* `America\/Indiana\/Vincennes` - America\/Indiana\/Vincennes\n\* `America\/Indiana\/Winamac` - America\/Indiana\/Winamac\n\* `America\/Indianapolis` - America\/Indianapolis\n\* `America\/Inuvik` - America\/Inuvik\n\* `America\/Iqaluit` - America\/Iqaluit\n\* `America\/Jamaica` - America\/Jamaica\n\* `America\/Jujuy` - America\/Jujuy\n\* `America\/Juneau` - America\/Juneau\n\* `America\/Kentucky\/Louisville` - America\/Kentucky\/Louisville\n\* `America\/Kentucky\/Monticello` - America\/Kentucky\/Monticello\n\* `America\/Knox_IN` - America\/Knox_IN\n\* `America\/Kralendijk` - America\/Kralendijk\n\* `America\/La_Paz` - America\/La_Paz\n\* `America\/Lima` - America\/Lima\n\* `America\/Los_Angeles` - America\/Los_Angeles\n\* `America\/Louisville` - America\/Louisville\n\* `America\/Lower_Princes` - America\/Lower_Princes\n\* `America\/Maceio` - America\/Maceio\n\* `America\/Managua` - America\/Managua\n\* `America\/Manaus` - America\/Manaus\n\* `America\/Marigot` - America\/Marigot\n\* `America\/Martinique` - America\/Martinique\n\* `America\/Matamoros` - America\/Matamoros\n\* `America\/Mazatlan` - America\/Mazatlan\n\* `America\/Mendoza` - America\/Mendoza\n\* `America\/Menominee` - America\/Menominee\n\* `America\/Merida` - America\/Merida\n\* `America\/Metlakatla` - America\/Metlakatla\n\* `America\/Mexico_City` - America\/Mexico_City\n\* `America\/Miquelon` - America\/Miquelon\n\* `America\/Moncton` - America\/Moncton\n\* `America\/Monterrey` - America\/Monterrey\n\* `America\/Montevideo` - America\/Montevideo\n\* `America\/Montreal` - America\/Montreal\n\* `America\/Montserrat` - America\/Montserrat\n\* `America\/Nassau` - America\/Nassau\n\* `America\/New_York` - America\/New_York\n\* `America\/Nipigon` - America\/Nipigon\n\* `America\/Nome` - America\/Nome\n\* `America\/Noronha` - America\/Noronha\n\* `America\/North_Dakota\/Beulah` - America\/North_Dakota\/Beulah\n\* `America\/North_Dakota\/Center` - America\/North_Dakota\/Center\n\* `America\/North_Dakota\/New_Salem` - America\/North_Dakota\/New_Salem\n\* `America\/Nuuk` - America\/Nuuk\n\* `America\/Ojinaga` - America\/Ojinaga\n\* `America\/Panama` - America\/Panama\n\* `America\/Pangnirtung` - America\/Pangnirtung\n\* `America\/Paramaribo` - America\/Paramaribo\n\* `America\/Phoenix` - America\/Phoenix\n\* `America\/Port-au-Prince` - America\/Port-au-Prince\n\* `America\/Port_of_Spain` - America\/Port_of_Spain\n\* `America\/Porto_Acre` - America\/Porto_Acre\n\* `America\/Porto_Velho` - America\/Porto_Velho\n\* `America\/Puerto_Rico` - America\/Puerto_Rico\n\* `America\/Punta_Arenas` - America\/Punta_Arenas\n\* `America\/Rainy_River` - America\/Rainy_River\n\* `America\/Rankin_Inlet` - America\/Rankin_Inlet\n\* `America\/Recife` - America\/Recife\n\* `America\/Regina` - America\/Regina\n\* `America\/Resolute` - America\/Resolute\n\* `America\/Rio_Branco` - America\/Rio_Branco\n\* `America\/Rosario` - America\/Rosario\n\* `America\/Santa_Isabel` - America\/Santa_Isabel\n\* `America\/Santarem` - America\/Santarem\n\* `America\/Santiago` - America\/Santiago\n\* `America\/Santo_Domingo` - America\/Santo_Domingo\n\* `America\/Sao_Paulo` - America\/Sao_Paulo\n\* `America\/Scoresbysund` - America\/Scoresbysund\n\* `America\/Shiprock` - America\/Shiprock\n\* `America\/Sitka` - America\/Sitka\n\* `America\/St_Barthelemy` - America\/St_Barthelemy\n\* `America\/St_Johns` - America\/St_Johns\n\* `America\/St_Kitts` - America\/St_Kitts\n\* `America\/St_Lucia` - America\/St_Lucia\n\* `America\/St_Thomas` - America\/St_Thomas\n\* `America\/St_Vincent` - America\/St_Vincent\n\* `America\/Swift_Current` - America\/Swift_Current\n\* `America\/Tegucigalpa` - America\/Tegucigalpa\n\* `America\/Thule` - America\/Thule\n\* `America\/Thunder_Bay` - America\/Thunder_Bay\n\* `America\/Tijuana` - America\/Tijuana\n\* `America\/Toronto` - America\/Toronto\n\* `America\/Tortola` - America\/Tortola\n\* `America\/Vancouver` - America\/Vancouver\n\* `America\/Virgin` - America\/Virgin\n\* `America\/Whitehorse` - America\/Whitehorse\n\* `America\/Winnipeg` - America\/Winnipeg\n\* `America\/Yakutat` - America\/Yakutat\n\* `America\/Yellowknife` - America\/Yellowknife\n\* `Antarctica\/Casey` - Antarctica\/Casey\n\* `Antarctica\/Davis` - Antarctica\/Davis\n\* `Antarctica\/DumontDUrville` - Antarctica\/DumontDUrville\n\* `Antarctica\/Macquarie` - Antarctica\/Macquarie\n\* `Antarctica\/Mawson` - Antarctica\/Mawson\n\* `Antarctica\/McMurdo` - Antarctica\/McMurdo\n\* `Antarctica\/Palmer` - Antarctica\/Palmer\n\* `Antarctica\/Rothera` - Antarctica\/Rothera\n\* `Antarctica\/South_Pole` - Antarctica\/South_Pole\n\* `Antarctica\/Syowa` - Antarctica\/Syowa\n\* `Antarctica\/Troll` - Antarctica\/Troll\n\* `Antarctica\/Vostok` - Antarctica\/Vostok\n\* `Arctic\/Longyearbyen` - Arctic\/Longyearbyen\n\* `Asia\/Aden` - Asia\/Aden\n\* `Asia\/Almaty` - Asia\/Almaty\n\* `Asia\/Amman` - Asia\/Amman\n\* `Asia\/Anadyr` - Asia\/Anadyr\n\* `Asia\/Aqtau` - Asia\/Aqtau\n\* `Asia\/Aqtobe` - Asia\/Aqtobe\n\* `Asia\/Ashgabat` - Asia\/Ashgabat\n\* `Asia\/Ashkhabad` - Asia\/Ashkhabad\n\* `Asia\/Atyrau` - Asia\/Atyrau\n\* `Asia\/Baghdad` - Asia\/Baghdad\n\* `Asia\/Bahrain` - Asia\/Bahrain\n\* `Asia\/Baku` - Asia\/Baku\n\* `Asia\/Bangkok` - Asia\/Bangkok\n\* `Asia\/Barnaul` - Asia\/Barnaul\n\* `Asia\/Beirut` - Asia\/Beirut\n\* `Asia\/Bishkek` - Asia\/Bishkek\n\* `Asia\/Brunei` - Asia\/Brunei\n\* `Asia\/Calcutta` - Asia\/Calcutta\n\* `Asia\/Chita` - Asia\/Chita\n\* `Asia\/Choibalsan` - Asia\/Choibalsan\n\* `Asia\/Chongqing` - Asia\/Chongqing\n\* `Asia\/Chungking` - Asia\/Chungking\n\* `Asia\/Colombo` - Asia\/Colombo\n\* `Asia\/Dacca` - Asia\/Dacca\n\* `Asia\/Damascus` - Asia\/Damascus\n\* `Asia\/Dhaka` - Asia\/Dhaka\n\* `Asia\/Dili` - Asia\/Dili\n\* `Asia\/Dubai` - Asia\/Dubai\n\* `Asia\/Dushanbe` - Asia\/Dushanbe\n\* `Asia\/Famagusta` - Asia\/Famagusta\n\* `Asia\/Gaza` - Asia\/Gaza\n\* `Asia\/Harbin` - Asia\/Harbin\n\* `Asia\/Hebron` - Asia\/Hebron\n\* `Asia\/Ho_Chi_Minh` - Asia\/Ho_Chi_Minh\n\* `Asia\/Hong_Kong` - Asia\/Hong_Kong\n\* `Asia\/Hovd` - Asia\/Hovd\n\* `Asia\/Irkutsk` - Asia\/Irkutsk\n\* `Asia\/Istanbul` - Asia\/Istanbul\n\* `Asia\/Jakarta` - Asia\/Jakarta\n\* `Asia\/Jayapura` - Asia\/Jayapura\n\* `Asia\/Jerusalem` - Asia\/Jerusalem\n\* `Asia\/Kabul` - Asia\/Kabul\n\* `Asia\/Kamchatka` - Asia\/Kamchatka\n\* `Asia\/Karachi` - Asia\/Karachi\n\* `Asia\/Kashgar` - Asia\/Kashgar\n\* `Asia\/Kathmandu` - Asia\/Kathmandu\n\* `Asia\/Katmandu` - Asia\/Katmandu\n\* `Asia\/Khandyga` - Asia\/Khandyga\n\* `Asia\/Kolkata` - Asia\/Kolkata\n\* `Asia\/Krasnoyarsk` - Asia\/Krasnoyarsk\n\* `Asia\/Kuala_Lumpur` - Asia\/Kuala_Lumpur\n\* `Asia\/Kuching` - Asia\/Kuching\n\* `Asia\/Kuwait` - Asia\/Kuwait\n\* `Asia\/Macao` - Asia\/Macao\n\* `Asia\/Macau` - Asia\/Macau\n\* `Asia\/Magadan` - Asia\/Magadan\n\* `Asia\/Makassar` - Asia\/Makassar\n\* `Asia\/Manila` - Asia\/Manila\n\* `Asia\/Muscat` - Asia\/Muscat\n\* `Asia\/Nicosia` - Asia\/Nicosia\n\* `Asia\/Novokuznetsk` - Asia\/Novokuznetsk\n\* `Asia\/Novosibirsk` - Asia\/Novosibirsk\n\* `Asia\/Omsk` - Asia\/Omsk\n\* `Asia\/Oral` - Asia\/Oral\n\* `Asia\/Phnom_Penh` - Asia\/Phnom_Penh\n\* `Asia\/Pontianak` - Asia\/Pontianak\n\* `Asia\/Pyongyang` - Asia\/Pyongyang\n\* `Asia\/Qatar` - Asia\/Qatar\n\* `Asia\/Qostanay` - Asia\/Qostanay\n\* `Asia\/Qyzylorda` - Asia\/Qyzylorda\n\* `Asia\/Rangoon` - Asia\/Rangoon\n\* `Asia\/Riyadh` - Asia\/Riyadh\n\* `Asia\/Saigon` - Asia\/Saigon\n\* `Asia\/Sakhalin` - Asia\/Sakhalin\n\* `Asia\/Samarkand` - Asia\/Samarkand\n\* `Asia\/Seoul` - Asia\/Seoul\n\* `Asia\/Shanghai` - Asia\/Shanghai\n\* `Asia\/Singapore` - Asia\/Singapore\n\* `Asia\/Srednekolymsk` - Asia\/Srednekolymsk\n\* `Asia\/Taipei` - Asia\/Taipei\n\* `Asia\/Tashkent` - Asia\/Tashkent\n\* `Asia\/Tbilisi` - Asia\/Tbilisi\n\* `Asia\/Tehran` - Asia\/Tehran\n\* `Asia\/Tel_Aviv` - Asia\/Tel_Aviv\n\* `Asia\/Thimbu` - Asia\/Thimbu\n\* `Asia\/Thimphu` - Asia\/Thimphu\n\* `Asia\/Tokyo` - Asia\/Tokyo\n\* `Asia\/Tomsk` - Asia\/Tomsk\n\* `Asia\/Ujung_Pandang` - Asia\/Ujung_Pandang\n\* `Asia\/Ulaanbaatar` - Asia\/Ulaanbaatar\n\* `Asia\/Ulan_Bator` - Asia\/Ulan_Bator\n\* `Asia\/Urumqi` - Asia\/Urumqi\n\* `Asia\/Ust-Nera` - Asia\/Ust-Nera\n\* `Asia\/Vientiane` - Asia\/Vientiane\n\* `Asia\/Vladivostok` - Asia\/Vladivostok\n\* `Asia\/Yakutsk` - Asia\/Yakutsk\n\* `Asia\/Yangon` - Asia\/Yangon\n\* `Asia\/Yekaterinburg` - Asia\/Yekaterinburg\n\* `Asia\/Yerevan` - Asia\/Yerevan\n\* `Atlantic\/Azores` - Atlantic\/Azores\n\* `Atlantic\/Bermuda` - Atlantic\/Bermuda\n\* `Atlantic\/Canary` - Atlantic\/Canary\n\* `Atlantic\/Cape_Verde` - Atlantic\/Cape_Verde\n\* `Atlantic\/Faeroe` - Atlantic\/Faeroe\n\* `Atlantic\/Faroe` - Atlantic\/Faroe\n\* `Atlantic\/Jan_Mayen` - Atlantic\/Jan_Mayen\n\* `Atlantic\/Madeira` - Atlantic\/Madeira\n\* `Atlantic\/Reykjavik` - Atlantic\/Reykjavik\n\* `Atlantic\/South_Georgia` - Atlantic\/South_Georgia\n\* `Atlantic\/St_Helena` - Atlantic\/St_Helena\n\* `Atlantic\/Stanley` - Atlantic\/Stanley\n\* `Australia\/ACT` - Australia\/ACT\n\* `Australia\/Adelaide` - Australia\/Adelaide\n\* `Australia\/Brisbane` - Australia\/Brisbane\n\* `Australia\/Broken_Hill` - Australia\/Broken_Hill\n\* `Australia\/Canberra` - Australia\/Canberra\n\* `Australia\/Currie` - Australia\/Currie\n\* `Australia\/Darwin` - Australia\/Darwin\n\* `Australia\/Eucla` - Australia\/Eucla\n\* `Australia\/Hobart` - Australia\/Hobart\n\* `Australia\/LHI` - Australia\/LHI\n\* `Australia\/Lindeman` - Australia\/Lindeman\n\* `Australia\/Lord_Howe` - Australia\/Lord_Howe\n\* `Australia\/Melbourne` - Australia\/Melbourne\n\* `Australia\/NSW` - Australia\/NSW\n\* `Australia\/North` - Australia\/North\n\* `Australia\/Perth` - Australia\/Perth\n\* `Australia\/Queensland` - Australia\/Queensland\n\* `Australia\/South` - Australia\/South\n\* `Australia\/Sydney` - Australia\/Sydney\n\* `Australia\/Tasmania` - Australia\/Tasmania\n\* `Australia\/Victoria` - Australia\/Victoria\n\* `Australia\/West` - Australia\/West\n\* `Australia\/Yancowinna` - Australia\/Yancowinna\n\* `Brazil\/Acre` - Brazil\/Acre\n\* `Brazil\/DeNoronha` - Brazil\/DeNoronha\n\* `Brazil\/East` - Brazil\/East\n\* `Brazil\/West` - Brazil\/West\n\* `CET` - CET\n\* `CST6CDT` - CST6CDT\n\* `Canada\/Atlantic` - Canada\/Atlantic\n\* `Canada\/Central` - Canada\/Central\n\* `Canada\/Eastern` - Canada\/Eastern\n\* `Canada\/Mountain` - Canada\/Mountain\n\* `Canada\/Newfoundland` - Canada\/Newfoundland\n\* `Canada\/Pacific` - Canada\/Pacific\n\* `Canada\/Saskatchewan` - Canada\/Saskatchewan\n\* `Canada\/Yukon` - Canada\/Yukon\n\* `Chile\/Continental` - Chile\/Continental\n\* `Chile\/EasterIsland` - Chile\/EasterIsland\n\* `Cuba` - Cuba\n\* `EET` - EET\n\* `EST` - EST\n\* `EST5EDT` - EST5EDT\n\* `Egypt` - Egypt\n\* `Eire` - Eire\n\* `Etc\/GMT` - Etc\/GMT\n\* `Etc\/GMT+0` - Etc\/GMT+0\n\* `Etc\/GMT+1` - Etc\/GMT+1\n\* `Etc\/GMT+10` - Etc\/GMT+10\n\* `Etc\/GMT+11` - Etc\/GMT+11\n\* `Etc\/GMT+12` - Etc\/GMT+12\n\* `Etc\/GMT+2` - Etc\/GMT+2\n\* `Etc\/GMT+3` - Etc\/GMT+3\n\* `Etc\/GMT+4` - Etc\/GMT+4\n\* `Etc\/GMT+5` - Etc\/GMT+5\n\* `Etc\/GMT+6` - Etc\/GMT+6\n\* `Etc\/GMT+7` - Etc\/GMT+7\n\* `Etc\/GMT+8` - Etc\/GMT+8\n\* `Etc\/GMT+9` - Etc\/GMT+9\n\* `Etc\/GMT-0` - Etc\/GMT-0\n\* `Etc\/GMT-1` - Etc\/GMT-1\n\* `Etc\/GMT-10` - Etc\/GMT-10\n\* `Etc\/GMT-11` - Etc\/GMT-11\n\* `Etc\/GMT-12` - Etc\/GMT-12\n\* `Etc\/GMT-13` - Etc\/GMT-13\n\* `Etc\/GMT-14` - Etc\/GMT-14\n\* `Etc\/GMT-2` - Etc\/GMT-2\n\* `Etc\/GMT-3` - Etc\/GMT-3\n\* `Etc\/GMT-4` - Etc\/GMT-4\n\* `Etc\/GMT-5` - Etc\/GMT-5\n\* `Etc\/GMT-6` - Etc\/GMT-6\n\* `Etc\/GMT-7` - Etc\/GMT-7\n\* `Etc\/GMT-8` - Etc\/GMT-8\n\* `Etc\/GMT-9` - Etc\/GMT-9\n\* `Etc\/GMT0` - Etc\/GMT0\n\* `Etc\/Greenwich` - Etc\/Greenwich\n\* `Etc\/UCT` - Etc\/UCT\n\* `Etc\/UTC` - Etc\/UTC\n\* `Etc\/Universal` - Etc\/Universal\n\* `Etc\/Zulu` - Etc\/Zulu\n\* `Europe\/Amsterdam` - Europe\/Amsterdam\n\* `Europe\/Andorra` - Europe\/Andorra\n\* `Europe\/Astrakhan` - Europe\/Astrakhan\n\* `Europe\/Athens` - Europe\/Athens\n\* `Europe\/Belfast` - Europe\/Belfast\n\* `Europe\/Belgrade` - Europe\/Belgrade\n\* `Europe\/Berlin` - Europe\/Berlin\n\* `Europe\/Bratislava` - Europe\/Bratislava\n\* `Europe\/Brussels` - Europe\/Brussels\n\* `Europe\/Bucharest` - Europe\/Bucharest\n\* `Europe\/Budapest` - Europe\/Budapest\n\* `Europe\/Busingen` - Europe\/Busingen\n\* `Europe\/Chisinau` - Europe\/Chisinau\n\* `Europe\/Copenhagen` - Europe\/Copenhagen\n\* `Europe\/Dublin` - Europe\/Dublin\n\* `Europe\/Gibraltar` - Europe\/Gibraltar\n\* `Europe\/Guernsey` - Europe\/Guernsey\n\* `Europe\/Helsinki` - Europe\/Helsinki\n\* `Europe\/Isle_of_Man` - Europe\/Isle_of_Man\n\* `Europe\/Istanbul` - Europe\/Istanbul\n\* `Europe\/Jersey` - Europe\/Jersey\n\* `Europe\/Kaliningrad` - Europe\/Kaliningrad\n\* `Europe\/Kiev` - Europe\/Kiev\n\* `Europe\/Kirov` - Europe\/Kirov\n\* `Europe\/Kyiv` - Europe\/Kyiv\n\* `Europe\/Lisbon` - Europe\/Lisbon\n\* `Europe\/Ljubljana` - Europe\/Ljubljana\n\* `Europe\/London` - Europe\/London\n\* `Europe\/Luxembourg` - Europe\/Luxembourg\n\* `Europe\/Madrid` - Europe\/Madrid\n\* `Europe\/Malta` - Europe\/Malta\n\* `Europe\/Mariehamn` - Europe\/Mariehamn\n\* `Europe\/Minsk` - Europe\/Minsk\n\* `Europe\/Monaco` - Europe\/Monaco\n\* `Europe\/Moscow` - Europe\/Moscow\n\* `Europe\/Nicosia` - Europe\/Nicosia\n\* `Europe\/Oslo` - Europe\/Oslo\n\* `Europe\/Paris` - Europe\/Paris\n\* `Europe\/Podgorica` - Europe\/Podgorica\n\* `Europe\/Prague` - Europe\/Prague\n\* `Europe\/Riga` - Europe\/Riga\n\* `Europe\/Rome` - Europe\/Rome\n\* `Europe\/Samara` - Europe\/Samara\n\* `Europe\/San_Marino` - Europe\/San_Marino\n\* `Europe\/Sarajevo` - Europe\/Sarajevo\n\* `Europe\/Saratov` - Europe\/Saratov\n\* `Europe\/Simferopol` - Europe\/Simferopol\n\* `Europe\/Skopje` - Europe\/Skopje\n\* `Europe\/Sofia` - Europe\/Sofia\n\* `Europe\/Stockholm` - Europe\/Stockholm\n\* `Europe\/Tallinn` - Europe\/Tallinn\n\* `Europe\/Tirane` - Europe\/Tirane\n\* `Europe\/Tiraspol` - Europe\/Tiraspol\n\* `Europe\/Ulyanovsk` - Europe\/Ulyanovsk\n\* `Europe\/Uzhgorod` - Europe\/Uzhgorod\n\* `Europe\/Vaduz` - Europe\/Vaduz\n\* `Europe\/Vatican` - Europe\/Vatican\n\* `Europe\/Vienna` - Europe\/Vienna\n\* `Europe\/Vilnius` - Europe\/Vilnius\n\* `Europe\/Volgograd` - Europe\/Volgograd\n\* `Europe\/Warsaw` - Europe\/Warsaw\n\* `Europe\/Zagreb` - Europe\/Zagreb\n\* `Europe\/Zaporozhye` - Europe\/Zaporozhye\n\* `Europe\/Zurich` - Europe\/Zurich\n\* `GB` - GB\n\* `GB-Eire` - GB-Eire\n\* `GMT` - GMT\n\* `GMT+0` - GMT+0\n\* `GMT-0` - GMT-0\n\* `GMT0` - GMT0\n\* `Greenwich` - Greenwich\n\* `HST` - HST\n\* `Hongkong` - Hongkong\n\* `Iceland` - Iceland\n\* `Indian\/Antananarivo` - Indian\/Antananarivo\n\* `Indian\/Chagos` - Indian\/Chagos\n\* `Indian\/Christmas` - Indian\/Christmas\n\* `Indian\/Cocos` - Indian\/Cocos\n\* `Indian\/Comoro` - Indian\/Comoro\n\* `Indian\/Kerguelen` - Indian\/Kerguelen\n\* `Indian\/Mahe` - Indian\/Mahe\n\* `Indian\/Maldives` - Indian\/Maldives\n\* `Indian\/Mauritius` - Indian\/Mauritius\n\* `Indian\/Mayotte` - Indian\/Mayotte\n\* `Indian\/Reunion` - Indian\/Reunion\n\* `Iran` - Iran\n\* `Israel` - Israel\n\* `Jamaica` - Jamaica\n\* `Japan` - Japan\n\* `Kwajalein` - Kwajalein\n\* `Libya` - Libya\n\* `MET` - MET\n\* `MST` - MST\n\* `MST7MDT` - MST7MDT\n\* `Mexico\/BajaNorte` - Mexico\/BajaNorte\n\* `Mexico\/BajaSur` - Mexico\/BajaSur\n\* `Mexico\/General` - Mexico\/General\n\* `NZ` - NZ\n\* `NZ-CHAT` - NZ-CHAT\n\* `Navajo` - Navajo\n\* `PRC` - PRC\n\* `PST8PDT` - PST8PDT\n\* `Pacific\/Apia` - Pacific\/Apia\n\* `Pacific\/Auckland` - Pacific\/Auckland\n\* `Pacific\/Bougainville` - Pacific\/Bougainville\n\* `Pacific\/Chatham` - Pacific\/Chatham\n\* `Pacific\/Chuuk` - Pacific\/Chuuk\n\* `Pacific\/Easter` - Pacific\/Easter\n\* `Pacific\/Efate` - Pacific\/Efate\n\* `Pacific\/Enderbury` - Pacific\/Enderbury\n\* `Pacific\/Fakaofo` - Pacific\/Fakaofo\n\* `Pacific\/Fiji` - Pacific\/Fiji\n\* `Pacific\/Funafuti` - Pacific\/Funafuti\n\* `Pacific\/Galapagos` - Pacific\/Galapagos\n\* `Pacific\/Gambier` - Pacific\/Gambier\n\* `Pacific\/Guadalcanal` - Pacific\/Guadalcanal\n\* `Pacific\/Guam` - Pacific\/Guam\n\* `Pacific\/Honolulu` - Pacific\/Honolulu\n\* `Pacific\/Johnston` - Pacific\/Johnston\n\* `Pacific\/Kanton` - Pacific\/Kanton\n\* `Pacific\/Kiritimati` - Pacific\/Kiritimati\n\* `Pacific\/Kosrae` - Pacific\/Kosrae\n\* `Pacific\/Kwajalein` - Pacific\/Kwajalein\n\* `Pacific\/Majuro` - Pacific\/Majuro\n\* `Pacific\/Marquesas` - Pacific\/Marquesas\n\* `Pacific\/Midway` - Pacific\/Midway\n\* `Pacific\/Nauru` - Pacific\/Nauru\n\* `Pacific\/Niue` - Pacific\/Niue\n\* `Pacific\/Norfolk` - Pacific\/Norfolk\n\* `Pacific\/Noumea` - Pacific\/Noumea\n\* `Pacific\/Pago_Pago` - Pacific\/Pago_Pago\n\* `Pacific\/Palau` - Pacific\/Palau\n\* `Pacific\/Pitcairn` - Pacific\/Pitcairn\n\* `Pacific\/Pohnpei` - Pacific\/Pohnpei\n\* `Pacific\/Ponape` - Pacific\/Ponape\n\* `Pacific\/Port_Moresby` - Pacific\/Port_Moresby\n\* `Pacific\/Rarotonga` - Pacific\/Rarotonga\n\* `Pacific\/Saipan` - Pacific\/Saipan\n\* `Pacific\/Samoa` - Pacific\/Samoa\n\* `Pacific\/Tahiti` - Pacific\/Tahiti\n\* `Pacific\/Tarawa` - Pacific\/Tarawa\n\* `Pacific\/Tongatapu` - Pacific\/Tongatapu\n\* `Pacific\/Truk` - Pacific\/Truk\n\* `Pacific\/Wake` - Pacific\/Wake\n\* `Pacific\/Wallis` - Pacific\/Wallis\n\* `Pacific\/Yap` - Pacific\/Yap\n\* `Poland` - Poland\n\* `Portugal` - Portugal\n\* `ROC` - ROC\n\* `ROK` - ROK\n\* `Singapore` - Singapore\n\* `Turkey` - Turkey\n\* `UCT` - UCT\n\* `US\/Alaska` - US\/Alaska\n\* `US\/Aleutian` - US\/Aleutian\n\* `US\/Arizona` - US\/Arizona\n\* `US\/Central` - US\/Central\n\* `US\/East-Indiana` - US\/East-Indiana\n\* `US\/Eastern` - US\/Eastern\n\* `US\/Hawaii` - US\/Hawaii\n\* `US\/Indiana-Starke` - US\/Indiana-Starke\n\* `US\/Michigan` - US\/Michigan\n\* `US\/Mountain` - US\/Mountain\n\* `US\/Pacific` - US\/Pacific\n\* `US\/Samoa` - US\/Samoa\n\* `UTC` - UTC\n\* `Universal` - Universal\n\* `W-SU` - W-SU\n\* `WET` - WET\n\* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsDefaultReleaseConditionsUpdateBodyPersonDisplayNamePropertiesItemMax)
            )
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat(
                'decimal',
                organizationsProjectsDefaultReleaseConditionsUpdateBodySessionRecordingSampleRateRegExp
            )
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(organizationsProjectsDefaultReleaseConditionsUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(organizationsProjectsDefaultReleaseConditionsUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(organizationsProjectsDefaultReleaseConditionsUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('\* `0` - Sunday\n\* `1` - Monday'),
                zod.null(),
            ])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n\* `0` - Sunday\n\* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsDefaultReleaseConditionsUpdateBodyRecordingDomainsItemMax)
                    .nullable()
            )
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations \/ live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(
                        organizationsProjectsDefaultReleaseConditionsUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax
                    )
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsDefaultReleaseConditionsUpdateBodyDefaultDataThemeMin)
            .max(organizationsProjectsDefaultReleaseConditionsUpdateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Projects for the current organization.
 */
export const organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyNameMax = 200

export const organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyProductDescriptionMax = 1000

export const organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyAppUrlsItemMax = 200

export const organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsDeleteSecretTokenBackupPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(
                zod.string().max(organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyAppUrlsItemMax).nullable()
            )
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal\/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal\/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America\/Los_Angeles`).\n\n\* `Africa\/Abidjan` - Africa\/Abidjan\n\* `Africa\/Accra` - Africa\/Accra\n\* `Africa\/Addis_Ababa` - Africa\/Addis_Ababa\n\* `Africa\/Algiers` - Africa\/Algiers\n\* `Africa\/Asmara` - Africa\/Asmara\n\* `Africa\/Asmera` - Africa\/Asmera\n\* `Africa\/Bamako` - Africa\/Bamako\n\* `Africa\/Bangui` - Africa\/Bangui\n\* `Africa\/Banjul` - Africa\/Banjul\n\* `Africa\/Bissau` - Africa\/Bissau\n\* `Africa\/Blantyre` - Africa\/Blantyre\n\* `Africa\/Brazzaville` - Africa\/Brazzaville\n\* `Africa\/Bujumbura` - Africa\/Bujumbura\n\* `Africa\/Cairo` - Africa\/Cairo\n\* `Africa\/Casablanca` - Africa\/Casablanca\n\* `Africa\/Ceuta` - Africa\/Ceuta\n\* `Africa\/Conakry` - Africa\/Conakry\n\* `Africa\/Dakar` - Africa\/Dakar\n\* `Africa\/Dar_es_Salaam` - Africa\/Dar_es_Salaam\n\* `Africa\/Djibouti` - Africa\/Djibouti\n\* `Africa\/Douala` - Africa\/Douala\n\* `Africa\/El_Aaiun` - Africa\/El_Aaiun\n\* `Africa\/Freetown` - Africa\/Freetown\n\* `Africa\/Gaborone` - Africa\/Gaborone\n\* `Africa\/Harare` - Africa\/Harare\n\* `Africa\/Johannesburg` - Africa\/Johannesburg\n\* `Africa\/Juba` - Africa\/Juba\n\* `Africa\/Kampala` - Africa\/Kampala\n\* `Africa\/Khartoum` - Africa\/Khartoum\n\* `Africa\/Kigali` - Africa\/Kigali\n\* `Africa\/Kinshasa` - Africa\/Kinshasa\n\* `Africa\/Lagos` - Africa\/Lagos\n\* `Africa\/Libreville` - Africa\/Libreville\n\* `Africa\/Lome` - Africa\/Lome\n\* `Africa\/Luanda` - Africa\/Luanda\n\* `Africa\/Lubumbashi` - Africa\/Lubumbashi\n\* `Africa\/Lusaka` - Africa\/Lusaka\n\* `Africa\/Malabo` - Africa\/Malabo\n\* `Africa\/Maputo` - Africa\/Maputo\n\* `Africa\/Maseru` - Africa\/Maseru\n\* `Africa\/Mbabane` - Africa\/Mbabane\n\* `Africa\/Mogadishu` - Africa\/Mogadishu\n\* `Africa\/Monrovia` - Africa\/Monrovia\n\* `Africa\/Nairobi` - Africa\/Nairobi\n\* `Africa\/Ndjamena` - Africa\/Ndjamena\n\* `Africa\/Niamey` - Africa\/Niamey\n\* `Africa\/Nouakchott` - Africa\/Nouakchott\n\* `Africa\/Ouagadougou` - Africa\/Ouagadougou\n\* `Africa\/Porto-Novo` - Africa\/Porto-Novo\n\* `Africa\/Sao_Tome` - Africa\/Sao_Tome\n\* `Africa\/Timbuktu` - Africa\/Timbuktu\n\* `Africa\/Tripoli` - Africa\/Tripoli\n\* `Africa\/Tunis` - Africa\/Tunis\n\* `Africa\/Windhoek` - Africa\/Windhoek\n\* `America\/Adak` - America\/Adak\n\* `America\/Anchorage` - America\/Anchorage\n\* `America\/Anguilla` - America\/Anguilla\n\* `America\/Antigua` - America\/Antigua\n\* `America\/Araguaina` - America\/Araguaina\n\* `America\/Argentina\/Buenos_Aires` - America\/Argentina\/Buenos_Aires\n\* `America\/Argentina\/Catamarca` - America\/Argentina\/Catamarca\n\* `America\/Argentina\/ComodRivadavia` - America\/Argentina\/ComodRivadavia\n\* `America\/Argentina\/Cordoba` - America\/Argentina\/Cordoba\n\* `America\/Argentina\/Jujuy` - America\/Argentina\/Jujuy\n\* `America\/Argentina\/La_Rioja` - America\/Argentina\/La_Rioja\n\* `America\/Argentina\/Mendoza` - America\/Argentina\/Mendoza\n\* `America\/Argentina\/Rio_Gallegos` - America\/Argentina\/Rio_Gallegos\n\* `America\/Argentina\/Salta` - America\/Argentina\/Salta\n\* `America\/Argentina\/San_Juan` - America\/Argentina\/San_Juan\n\* `America\/Argentina\/San_Luis` - America\/Argentina\/San_Luis\n\* `America\/Argentina\/Tucuman` - America\/Argentina\/Tucuman\n\* `America\/Argentina\/Ushuaia` - America\/Argentina\/Ushuaia\n\* `America\/Aruba` - America\/Aruba\n\* `America\/Asuncion` - America\/Asuncion\n\* `America\/Atikokan` - America\/Atikokan\n\* `America\/Atka` - America\/Atka\n\* `America\/Bahia` - America\/Bahia\n\* `America\/Bahia_Banderas` - America\/Bahia_Banderas\n\* `America\/Barbados` - America\/Barbados\n\* `America\/Belem` - America\/Belem\n\* `America\/Belize` - America\/Belize\n\* `America\/Blanc-Sablon` - America\/Blanc-Sablon\n\* `America\/Boa_Vista` - America\/Boa_Vista\n\* `America\/Bogota` - America\/Bogota\n\* `America\/Boise` - America\/Boise\n\* `America\/Buenos_Aires` - America\/Buenos_Aires\n\* `America\/Cambridge_Bay` - America\/Cambridge_Bay\n\* `America\/Campo_Grande` - America\/Campo_Grande\n\* `America\/Cancun` - America\/Cancun\n\* `America\/Caracas` - America\/Caracas\n\* `America\/Catamarca` - America\/Catamarca\n\* `America\/Cayenne` - America\/Cayenne\n\* `America\/Cayman` - America\/Cayman\n\* `America\/Chicago` - America\/Chicago\n\* `America\/Chihuahua` - America\/Chihuahua\n\* `America\/Ciudad_Juarez` - America\/Ciudad_Juarez\n\* `America\/Coral_Harbour` - America\/Coral_Harbour\n\* `America\/Cordoba` - America\/Cordoba\n\* `America\/Costa_Rica` - America\/Costa_Rica\n\* `America\/Creston` - America\/Creston\n\* `America\/Cuiaba` - America\/Cuiaba\n\* `America\/Curacao` - America\/Curacao\n\* `America\/Danmarkshavn` - America\/Danmarkshavn\n\* `America\/Dawson` - America\/Dawson\n\* `America\/Dawson_Creek` - America\/Dawson_Creek\n\* `America\/Denver` - America\/Denver\n\* `America\/Detroit` - America\/Detroit\n\* `America\/Dominica` - America\/Dominica\n\* `America\/Edmonton` - America\/Edmonton\n\* `America\/Eirunepe` - America\/Eirunepe\n\* `America\/El_Salvador` - America\/El_Salvador\n\* `America\/Ensenada` - America\/Ensenada\n\* `America\/Fort_Nelson` - America\/Fort_Nelson\n\* `America\/Fort_Wayne` - America\/Fort_Wayne\n\* `America\/Fortaleza` - America\/Fortaleza\n\* `America\/Glace_Bay` - America\/Glace_Bay\n\* `America\/Godthab` - America\/Godthab\n\* `America\/Goose_Bay` - America\/Goose_Bay\n\* `America\/Grand_Turk` - America\/Grand_Turk\n\* `America\/Grenada` - America\/Grenada\n\* `America\/Guadeloupe` - America\/Guadeloupe\n\* `America\/Guatemala` - America\/Guatemala\n\* `America\/Guayaquil` - America\/Guayaquil\n\* `America\/Guyana` - America\/Guyana\n\* `America\/Halifax` - America\/Halifax\n\* `America\/Havana` - America\/Havana\n\* `America\/Hermosillo` - America\/Hermosillo\n\* `America\/Indiana\/Indianapolis` - America\/Indiana\/Indianapolis\n\* `America\/Indiana\/Knox` - America\/Indiana\/Knox\n\* `America\/Indiana\/Marengo` - America\/Indiana\/Marengo\n\* `America\/Indiana\/Petersburg` - America\/Indiana\/Petersburg\n\* `America\/Indiana\/Tell_City` - America\/Indiana\/Tell_City\n\* `America\/Indiana\/Vevay` - America\/Indiana\/Vevay\n\* `America\/Indiana\/Vincennes` - America\/Indiana\/Vincennes\n\* `America\/Indiana\/Winamac` - America\/Indiana\/Winamac\n\* `America\/Indianapolis` - America\/Indianapolis\n\* `America\/Inuvik` - America\/Inuvik\n\* `America\/Iqaluit` - America\/Iqaluit\n\* `America\/Jamaica` - America\/Jamaica\n\* `America\/Jujuy` - America\/Jujuy\n\* `America\/Juneau` - America\/Juneau\n\* `America\/Kentucky\/Louisville` - America\/Kentucky\/Louisville\n\* `America\/Kentucky\/Monticello` - America\/Kentucky\/Monticello\n\* `America\/Knox_IN` - America\/Knox_IN\n\* `America\/Kralendijk` - America\/Kralendijk\n\* `America\/La_Paz` - America\/La_Paz\n\* `America\/Lima` - America\/Lima\n\* `America\/Los_Angeles` - America\/Los_Angeles\n\* `America\/Louisville` - America\/Louisville\n\* `America\/Lower_Princes` - America\/Lower_Princes\n\* `America\/Maceio` - America\/Maceio\n\* `America\/Managua` - America\/Managua\n\* `America\/Manaus` - America\/Manaus\n\* `America\/Marigot` - America\/Marigot\n\* `America\/Martinique` - America\/Martinique\n\* `America\/Matamoros` - America\/Matamoros\n\* `America\/Mazatlan` - America\/Mazatlan\n\* `America\/Mendoza` - America\/Mendoza\n\* `America\/Menominee` - America\/Menominee\n\* `America\/Merida` - America\/Merida\n\* `America\/Metlakatla` - America\/Metlakatla\n\* `America\/Mexico_City` - America\/Mexico_City\n\* `America\/Miquelon` - America\/Miquelon\n\* `America\/Moncton` - America\/Moncton\n\* `America\/Monterrey` - America\/Monterrey\n\* `America\/Montevideo` - America\/Montevideo\n\* `America\/Montreal` - America\/Montreal\n\* `America\/Montserrat` - America\/Montserrat\n\* `America\/Nassau` - America\/Nassau\n\* `America\/New_York` - America\/New_York\n\* `America\/Nipigon` - America\/Nipigon\n\* `America\/Nome` - America\/Nome\n\* `America\/Noronha` - America\/Noronha\n\* `America\/North_Dakota\/Beulah` - America\/North_Dakota\/Beulah\n\* `America\/North_Dakota\/Center` - America\/North_Dakota\/Center\n\* `America\/North_Dakota\/New_Salem` - America\/North_Dakota\/New_Salem\n\* `America\/Nuuk` - America\/Nuuk\n\* `America\/Ojinaga` - America\/Ojinaga\n\* `America\/Panama` - America\/Panama\n\* `America\/Pangnirtung` - America\/Pangnirtung\n\* `America\/Paramaribo` - America\/Paramaribo\n\* `America\/Phoenix` - America\/Phoenix\n\* `America\/Port-au-Prince` - America\/Port-au-Prince\n\* `America\/Port_of_Spain` - America\/Port_of_Spain\n\* `America\/Porto_Acre` - America\/Porto_Acre\n\* `America\/Porto_Velho` - America\/Porto_Velho\n\* `America\/Puerto_Rico` - America\/Puerto_Rico\n\* `America\/Punta_Arenas` - America\/Punta_Arenas\n\* `America\/Rainy_River` - America\/Rainy_River\n\* `America\/Rankin_Inlet` - America\/Rankin_Inlet\n\* `America\/Recife` - America\/Recife\n\* `America\/Regina` - America\/Regina\n\* `America\/Resolute` - America\/Resolute\n\* `America\/Rio_Branco` - America\/Rio_Branco\n\* `America\/Rosario` - America\/Rosario\n\* `America\/Santa_Isabel` - America\/Santa_Isabel\n\* `America\/Santarem` - America\/Santarem\n\* `America\/Santiago` - America\/Santiago\n\* `America\/Santo_Domingo` - America\/Santo_Domingo\n\* `America\/Sao_Paulo` - America\/Sao_Paulo\n\* `America\/Scoresbysund` - America\/Scoresbysund\n\* `America\/Shiprock` - America\/Shiprock\n\* `America\/Sitka` - America\/Sitka\n\* `America\/St_Barthelemy` - America\/St_Barthelemy\n\* `America\/St_Johns` - America\/St_Johns\n\* `America\/St_Kitts` - America\/St_Kitts\n\* `America\/St_Lucia` - America\/St_Lucia\n\* `America\/St_Thomas` - America\/St_Thomas\n\* `America\/St_Vincent` - America\/St_Vincent\n\* `America\/Swift_Current` - America\/Swift_Current\n\* `America\/Tegucigalpa` - America\/Tegucigalpa\n\* `America\/Thule` - America\/Thule\n\* `America\/Thunder_Bay` - America\/Thunder_Bay\n\* `America\/Tijuana` - America\/Tijuana\n\* `America\/Toronto` - America\/Toronto\n\* `America\/Tortola` - America\/Tortola\n\* `America\/Vancouver` - America\/Vancouver\n\* `America\/Virgin` - America\/Virgin\n\* `America\/Whitehorse` - America\/Whitehorse\n\* `America\/Winnipeg` - America\/Winnipeg\n\* `America\/Yakutat` - America\/Yakutat\n\* `America\/Yellowknife` - America\/Yellowknife\n\* `Antarctica\/Casey` - Antarctica\/Casey\n\* `Antarctica\/Davis` - Antarctica\/Davis\n\* `Antarctica\/DumontDUrville` - Antarctica\/DumontDUrville\n\* `Antarctica\/Macquarie` - Antarctica\/Macquarie\n\* `Antarctica\/Mawson` - Antarctica\/Mawson\n\* `Antarctica\/McMurdo` - Antarctica\/McMurdo\n\* `Antarctica\/Palmer` - Antarctica\/Palmer\n\* `Antarctica\/Rothera` - Antarctica\/Rothera\n\* `Antarctica\/South_Pole` - Antarctica\/South_Pole\n\* `Antarctica\/Syowa` - Antarctica\/Syowa\n\* `Antarctica\/Troll` - Antarctica\/Troll\n\* `Antarctica\/Vostok` - Antarctica\/Vostok\n\* `Arctic\/Longyearbyen` - Arctic\/Longyearbyen\n\* `Asia\/Aden` - Asia\/Aden\n\* `Asia\/Almaty` - Asia\/Almaty\n\* `Asia\/Amman` - Asia\/Amman\n\* `Asia\/Anadyr` - Asia\/Anadyr\n\* `Asia\/Aqtau` - Asia\/Aqtau\n\* `Asia\/Aqtobe` - Asia\/Aqtobe\n\* `Asia\/Ashgabat` - Asia\/Ashgabat\n\* `Asia\/Ashkhabad` - Asia\/Ashkhabad\n\* `Asia\/Atyrau` - Asia\/Atyrau\n\* `Asia\/Baghdad` - Asia\/Baghdad\n\* `Asia\/Bahrain` - Asia\/Bahrain\n\* `Asia\/Baku` - Asia\/Baku\n\* `Asia\/Bangkok` - Asia\/Bangkok\n\* `Asia\/Barnaul` - Asia\/Barnaul\n\* `Asia\/Beirut` - Asia\/Beirut\n\* `Asia\/Bishkek` - Asia\/Bishkek\n\* `Asia\/Brunei` - Asia\/Brunei\n\* `Asia\/Calcutta` - Asia\/Calcutta\n\* `Asia\/Chita` - Asia\/Chita\n\* `Asia\/Choibalsan` - Asia\/Choibalsan\n\* `Asia\/Chongqing` - Asia\/Chongqing\n\* `Asia\/Chungking` - Asia\/Chungking\n\* `Asia\/Colombo` - Asia\/Colombo\n\* `Asia\/Dacca` - Asia\/Dacca\n\* `Asia\/Damascus` - Asia\/Damascus\n\* `Asia\/Dhaka` - Asia\/Dhaka\n\* `Asia\/Dili` - Asia\/Dili\n\* `Asia\/Dubai` - Asia\/Dubai\n\* `Asia\/Dushanbe` - Asia\/Dushanbe\n\* `Asia\/Famagusta` - Asia\/Famagusta\n\* `Asia\/Gaza` - Asia\/Gaza\n\* `Asia\/Harbin` - Asia\/Harbin\n\* `Asia\/Hebron` - Asia\/Hebron\n\* `Asia\/Ho_Chi_Minh` - Asia\/Ho_Chi_Minh\n\* `Asia\/Hong_Kong` - Asia\/Hong_Kong\n\* `Asia\/Hovd` - Asia\/Hovd\n\* `Asia\/Irkutsk` - Asia\/Irkutsk\n\* `Asia\/Istanbul` - Asia\/Istanbul\n\* `Asia\/Jakarta` - Asia\/Jakarta\n\* `Asia\/Jayapura` - Asia\/Jayapura\n\* `Asia\/Jerusalem` - Asia\/Jerusalem\n\* `Asia\/Kabul` - Asia\/Kabul\n\* `Asia\/Kamchatka` - Asia\/Kamchatka\n\* `Asia\/Karachi` - Asia\/Karachi\n\* `Asia\/Kashgar` - Asia\/Kashgar\n\* `Asia\/Kathmandu` - Asia\/Kathmandu\n\* `Asia\/Katmandu` - Asia\/Katmandu\n\* `Asia\/Khandyga` - Asia\/Khandyga\n\* `Asia\/Kolkata` - Asia\/Kolkata\n\* `Asia\/Krasnoyarsk` - Asia\/Krasnoyarsk\n\* `Asia\/Kuala_Lumpur` - Asia\/Kuala_Lumpur\n\* `Asia\/Kuching` - Asia\/Kuching\n\* `Asia\/Kuwait` - Asia\/Kuwait\n\* `Asia\/Macao` - Asia\/Macao\n\* `Asia\/Macau` - Asia\/Macau\n\* `Asia\/Magadan` - Asia\/Magadan\n\* `Asia\/Makassar` - Asia\/Makassar\n\* `Asia\/Manila` - Asia\/Manila\n\* `Asia\/Muscat` - Asia\/Muscat\n\* `Asia\/Nicosia` - Asia\/Nicosia\n\* `Asia\/Novokuznetsk` - Asia\/Novokuznetsk\n\* `Asia\/Novosibirsk` - Asia\/Novosibirsk\n\* `Asia\/Omsk` - Asia\/Omsk\n\* `Asia\/Oral` - Asia\/Oral\n\* `Asia\/Phnom_Penh` - Asia\/Phnom_Penh\n\* `Asia\/Pontianak` - Asia\/Pontianak\n\* `Asia\/Pyongyang` - Asia\/Pyongyang\n\* `Asia\/Qatar` - Asia\/Qatar\n\* `Asia\/Qostanay` - Asia\/Qostanay\n\* `Asia\/Qyzylorda` - Asia\/Qyzylorda\n\* `Asia\/Rangoon` - Asia\/Rangoon\n\* `Asia\/Riyadh` - Asia\/Riyadh\n\* `Asia\/Saigon` - Asia\/Saigon\n\* `Asia\/Sakhalin` - Asia\/Sakhalin\n\* `Asia\/Samarkand` - Asia\/Samarkand\n\* `Asia\/Seoul` - Asia\/Seoul\n\* `Asia\/Shanghai` - Asia\/Shanghai\n\* `Asia\/Singapore` - Asia\/Singapore\n\* `Asia\/Srednekolymsk` - Asia\/Srednekolymsk\n\* `Asia\/Taipei` - Asia\/Taipei\n\* `Asia\/Tashkent` - Asia\/Tashkent\n\* `Asia\/Tbilisi` - Asia\/Tbilisi\n\* `Asia\/Tehran` - Asia\/Tehran\n\* `Asia\/Tel_Aviv` - Asia\/Tel_Aviv\n\* `Asia\/Thimbu` - Asia\/Thimbu\n\* `Asia\/Thimphu` - Asia\/Thimphu\n\* `Asia\/Tokyo` - Asia\/Tokyo\n\* `Asia\/Tomsk` - Asia\/Tomsk\n\* `Asia\/Ujung_Pandang` - Asia\/Ujung_Pandang\n\* `Asia\/Ulaanbaatar` - Asia\/Ulaanbaatar\n\* `Asia\/Ulan_Bator` - Asia\/Ulan_Bator\n\* `Asia\/Urumqi` - Asia\/Urumqi\n\* `Asia\/Ust-Nera` - Asia\/Ust-Nera\n\* `Asia\/Vientiane` - Asia\/Vientiane\n\* `Asia\/Vladivostok` - Asia\/Vladivostok\n\* `Asia\/Yakutsk` - Asia\/Yakutsk\n\* `Asia\/Yangon` - Asia\/Yangon\n\* `Asia\/Yekaterinburg` - Asia\/Yekaterinburg\n\* `Asia\/Yerevan` - Asia\/Yerevan\n\* `Atlantic\/Azores` - Atlantic\/Azores\n\* `Atlantic\/Bermuda` - Atlantic\/Bermuda\n\* `Atlantic\/Canary` - Atlantic\/Canary\n\* `Atlantic\/Cape_Verde` - Atlantic\/Cape_Verde\n\* `Atlantic\/Faeroe` - Atlantic\/Faeroe\n\* `Atlantic\/Faroe` - Atlantic\/Faroe\n\* `Atlantic\/Jan_Mayen` - Atlantic\/Jan_Mayen\n\* `Atlantic\/Madeira` - Atlantic\/Madeira\n\* `Atlantic\/Reykjavik` - Atlantic\/Reykjavik\n\* `Atlantic\/South_Georgia` - Atlantic\/South_Georgia\n\* `Atlantic\/St_Helena` - Atlantic\/St_Helena\n\* `Atlantic\/Stanley` - Atlantic\/Stanley\n\* `Australia\/ACT` - Australia\/ACT\n\* `Australia\/Adelaide` - Australia\/Adelaide\n\* `Australia\/Brisbane` - Australia\/Brisbane\n\* `Australia\/Broken_Hill` - Australia\/Broken_Hill\n\* `Australia\/Canberra` - Australia\/Canberra\n\* `Australia\/Currie` - Australia\/Currie\n\* `Australia\/Darwin` - Australia\/Darwin\n\* `Australia\/Eucla` - Australia\/Eucla\n\* `Australia\/Hobart` - Australia\/Hobart\n\* `Australia\/LHI` - Australia\/LHI\n\* `Australia\/Lindeman` - Australia\/Lindeman\n\* `Australia\/Lord_Howe` - Australia\/Lord_Howe\n\* `Australia\/Melbourne` - Australia\/Melbourne\n\* `Australia\/NSW` - Australia\/NSW\n\* `Australia\/North` - Australia\/North\n\* `Australia\/Perth` - Australia\/Perth\n\* `Australia\/Queensland` - Australia\/Queensland\n\* `Australia\/South` - Australia\/South\n\* `Australia\/Sydney` - Australia\/Sydney\n\* `Australia\/Tasmania` - Australia\/Tasmania\n\* `Australia\/Victoria` - Australia\/Victoria\n\* `Australia\/West` - Australia\/West\n\* `Australia\/Yancowinna` - Australia\/Yancowinna\n\* `Brazil\/Acre` - Brazil\/Acre\n\* `Brazil\/DeNoronha` - Brazil\/DeNoronha\n\* `Brazil\/East` - Brazil\/East\n\* `Brazil\/West` - Brazil\/West\n\* `CET` - CET\n\* `CST6CDT` - CST6CDT\n\* `Canada\/Atlantic` - Canada\/Atlantic\n\* `Canada\/Central` - Canada\/Central\n\* `Canada\/Eastern` - Canada\/Eastern\n\* `Canada\/Mountain` - Canada\/Mountain\n\* `Canada\/Newfoundland` - Canada\/Newfoundland\n\* `Canada\/Pacific` - Canada\/Pacific\n\* `Canada\/Saskatchewan` - Canada\/Saskatchewan\n\* `Canada\/Yukon` - Canada\/Yukon\n\* `Chile\/Continental` - Chile\/Continental\n\* `Chile\/EasterIsland` - Chile\/EasterIsland\n\* `Cuba` - Cuba\n\* `EET` - EET\n\* `EST` - EST\n\* `EST5EDT` - EST5EDT\n\* `Egypt` - Egypt\n\* `Eire` - Eire\n\* `Etc\/GMT` - Etc\/GMT\n\* `Etc\/GMT+0` - Etc\/GMT+0\n\* `Etc\/GMT+1` - Etc\/GMT+1\n\* `Etc\/GMT+10` - Etc\/GMT+10\n\* `Etc\/GMT+11` - Etc\/GMT+11\n\* `Etc\/GMT+12` - Etc\/GMT+12\n\* `Etc\/GMT+2` - Etc\/GMT+2\n\* `Etc\/GMT+3` - Etc\/GMT+3\n\* `Etc\/GMT+4` - Etc\/GMT+4\n\* `Etc\/GMT+5` - Etc\/GMT+5\n\* `Etc\/GMT+6` - Etc\/GMT+6\n\* `Etc\/GMT+7` - Etc\/GMT+7\n\* `Etc\/GMT+8` - Etc\/GMT+8\n\* `Etc\/GMT+9` - Etc\/GMT+9\n\* `Etc\/GMT-0` - Etc\/GMT-0\n\* `Etc\/GMT-1` - Etc\/GMT-1\n\* `Etc\/GMT-10` - Etc\/GMT-10\n\* `Etc\/GMT-11` - Etc\/GMT-11\n\* `Etc\/GMT-12` - Etc\/GMT-12\n\* `Etc\/GMT-13` - Etc\/GMT-13\n\* `Etc\/GMT-14` - Etc\/GMT-14\n\* `Etc\/GMT-2` - Etc\/GMT-2\n\* `Etc\/GMT-3` - Etc\/GMT-3\n\* `Etc\/GMT-4` - Etc\/GMT-4\n\* `Etc\/GMT-5` - Etc\/GMT-5\n\* `Etc\/GMT-6` - Etc\/GMT-6\n\* `Etc\/GMT-7` - Etc\/GMT-7\n\* `Etc\/GMT-8` - Etc\/GMT-8\n\* `Etc\/GMT-9` - Etc\/GMT-9\n\* `Etc\/GMT0` - Etc\/GMT0\n\* `Etc\/Greenwich` - Etc\/Greenwich\n\* `Etc\/UCT` - Etc\/UCT\n\* `Etc\/UTC` - Etc\/UTC\n\* `Etc\/Universal` - Etc\/Universal\n\* `Etc\/Zulu` - Etc\/Zulu\n\* `Europe\/Amsterdam` - Europe\/Amsterdam\n\* `Europe\/Andorra` - Europe\/Andorra\n\* `Europe\/Astrakhan` - Europe\/Astrakhan\n\* `Europe\/Athens` - Europe\/Athens\n\* `Europe\/Belfast` - Europe\/Belfast\n\* `Europe\/Belgrade` - Europe\/Belgrade\n\* `Europe\/Berlin` - Europe\/Berlin\n\* `Europe\/Bratislava` - Europe\/Bratislava\n\* `Europe\/Brussels` - Europe\/Brussels\n\* `Europe\/Bucharest` - Europe\/Bucharest\n\* `Europe\/Budapest` - Europe\/Budapest\n\* `Europe\/Busingen` - Europe\/Busingen\n\* `Europe\/Chisinau` - Europe\/Chisinau\n\* `Europe\/Copenhagen` - Europe\/Copenhagen\n\* `Europe\/Dublin` - Europe\/Dublin\n\* `Europe\/Gibraltar` - Europe\/Gibraltar\n\* `Europe\/Guernsey` - Europe\/Guernsey\n\* `Europe\/Helsinki` - Europe\/Helsinki\n\* `Europe\/Isle_of_Man` - Europe\/Isle_of_Man\n\* `Europe\/Istanbul` - Europe\/Istanbul\n\* `Europe\/Jersey` - Europe\/Jersey\n\* `Europe\/Kaliningrad` - Europe\/Kaliningrad\n\* `Europe\/Kiev` - Europe\/Kiev\n\* `Europe\/Kirov` - Europe\/Kirov\n\* `Europe\/Kyiv` - Europe\/Kyiv\n\* `Europe\/Lisbon` - Europe\/Lisbon\n\* `Europe\/Ljubljana` - Europe\/Ljubljana\n\* `Europe\/London` - Europe\/London\n\* `Europe\/Luxembourg` - Europe\/Luxembourg\n\* `Europe\/Madrid` - Europe\/Madrid\n\* `Europe\/Malta` - Europe\/Malta\n\* `Europe\/Mariehamn` - Europe\/Mariehamn\n\* `Europe\/Minsk` - Europe\/Minsk\n\* `Europe\/Monaco` - Europe\/Monaco\n\* `Europe\/Moscow` - Europe\/Moscow\n\* `Europe\/Nicosia` - Europe\/Nicosia\n\* `Europe\/Oslo` - Europe\/Oslo\n\* `Europe\/Paris` - Europe\/Paris\n\* `Europe\/Podgorica` - Europe\/Podgorica\n\* `Europe\/Prague` - Europe\/Prague\n\* `Europe\/Riga` - Europe\/Riga\n\* `Europe\/Rome` - Europe\/Rome\n\* `Europe\/Samara` - Europe\/Samara\n\* `Europe\/San_Marino` - Europe\/San_Marino\n\* `Europe\/Sarajevo` - Europe\/Sarajevo\n\* `Europe\/Saratov` - Europe\/Saratov\n\* `Europe\/Simferopol` - Europe\/Simferopol\n\* `Europe\/Skopje` - Europe\/Skopje\n\* `Europe\/Sofia` - Europe\/Sofia\n\* `Europe\/Stockholm` - Europe\/Stockholm\n\* `Europe\/Tallinn` - Europe\/Tallinn\n\* `Europe\/Tirane` - Europe\/Tirane\n\* `Europe\/Tiraspol` - Europe\/Tiraspol\n\* `Europe\/Ulyanovsk` - Europe\/Ulyanovsk\n\* `Europe\/Uzhgorod` - Europe\/Uzhgorod\n\* `Europe\/Vaduz` - Europe\/Vaduz\n\* `Europe\/Vatican` - Europe\/Vatican\n\* `Europe\/Vienna` - Europe\/Vienna\n\* `Europe\/Vilnius` - Europe\/Vilnius\n\* `Europe\/Volgograd` - Europe\/Volgograd\n\* `Europe\/Warsaw` - Europe\/Warsaw\n\* `Europe\/Zagreb` - Europe\/Zagreb\n\* `Europe\/Zaporozhye` - Europe\/Zaporozhye\n\* `Europe\/Zurich` - Europe\/Zurich\n\* `GB` - GB\n\* `GB-Eire` - GB-Eire\n\* `GMT` - GMT\n\* `GMT+0` - GMT+0\n\* `GMT-0` - GMT-0\n\* `GMT0` - GMT0\n\* `Greenwich` - Greenwich\n\* `HST` - HST\n\* `Hongkong` - Hongkong\n\* `Iceland` - Iceland\n\* `Indian\/Antananarivo` - Indian\/Antananarivo\n\* `Indian\/Chagos` - Indian\/Chagos\n\* `Indian\/Christmas` - Indian\/Christmas\n\* `Indian\/Cocos` - Indian\/Cocos\n\* `Indian\/Comoro` - Indian\/Comoro\n\* `Indian\/Kerguelen` - Indian\/Kerguelen\n\* `Indian\/Mahe` - Indian\/Mahe\n\* `Indian\/Maldives` - Indian\/Maldives\n\* `Indian\/Mauritius` - Indian\/Mauritius\n\* `Indian\/Mayotte` - Indian\/Mayotte\n\* `Indian\/Reunion` - Indian\/Reunion\n\* `Iran` - Iran\n\* `Israel` - Israel\n\* `Jamaica` - Jamaica\n\* `Japan` - Japan\n\* `Kwajalein` - Kwajalein\n\* `Libya` - Libya\n\* `MET` - MET\n\* `MST` - MST\n\* `MST7MDT` - MST7MDT\n\* `Mexico\/BajaNorte` - Mexico\/BajaNorte\n\* `Mexico\/BajaSur` - Mexico\/BajaSur\n\* `Mexico\/General` - Mexico\/General\n\* `NZ` - NZ\n\* `NZ-CHAT` - NZ-CHAT\n\* `Navajo` - Navajo\n\* `PRC` - PRC\n\* `PST8PDT` - PST8PDT\n\* `Pacific\/Apia` - Pacific\/Apia\n\* `Pacific\/Auckland` - Pacific\/Auckland\n\* `Pacific\/Bougainville` - Pacific\/Bougainville\n\* `Pacific\/Chatham` - Pacific\/Chatham\n\* `Pacific\/Chuuk` - Pacific\/Chuuk\n\* `Pacific\/Easter` - Pacific\/Easter\n\* `Pacific\/Efate` - Pacific\/Efate\n\* `Pacific\/Enderbury` - Pacific\/Enderbury\n\* `Pacific\/Fakaofo` - Pacific\/Fakaofo\n\* `Pacific\/Fiji` - Pacific\/Fiji\n\* `Pacific\/Funafuti` - Pacific\/Funafuti\n\* `Pacific\/Galapagos` - Pacific\/Galapagos\n\* `Pacific\/Gambier` - Pacific\/Gambier\n\* `Pacific\/Guadalcanal` - Pacific\/Guadalcanal\n\* `Pacific\/Guam` - Pacific\/Guam\n\* `Pacific\/Honolulu` - Pacific\/Honolulu\n\* `Pacific\/Johnston` - Pacific\/Johnston\n\* `Pacific\/Kanton` - Pacific\/Kanton\n\* `Pacific\/Kiritimati` - Pacific\/Kiritimati\n\* `Pacific\/Kosrae` - Pacific\/Kosrae\n\* `Pacific\/Kwajalein` - Pacific\/Kwajalein\n\* `Pacific\/Majuro` - Pacific\/Majuro\n\* `Pacific\/Marquesas` - Pacific\/Marquesas\n\* `Pacific\/Midway` - Pacific\/Midway\n\* `Pacific\/Nauru` - Pacific\/Nauru\n\* `Pacific\/Niue` - Pacific\/Niue\n\* `Pacific\/Norfolk` - Pacific\/Norfolk\n\* `Pacific\/Noumea` - Pacific\/Noumea\n\* `Pacific\/Pago_Pago` - Pacific\/Pago_Pago\n\* `Pacific\/Palau` - Pacific\/Palau\n\* `Pacific\/Pitcairn` - Pacific\/Pitcairn\n\* `Pacific\/Pohnpei` - Pacific\/Pohnpei\n\* `Pacific\/Ponape` - Pacific\/Ponape\n\* `Pacific\/Port_Moresby` - Pacific\/Port_Moresby\n\* `Pacific\/Rarotonga` - Pacific\/Rarotonga\n\* `Pacific\/Saipan` - Pacific\/Saipan\n\* `Pacific\/Samoa` - Pacific\/Samoa\n\* `Pacific\/Tahiti` - Pacific\/Tahiti\n\* `Pacific\/Tarawa` - Pacific\/Tarawa\n\* `Pacific\/Tongatapu` - Pacific\/Tongatapu\n\* `Pacific\/Truk` - Pacific\/Truk\n\* `Pacific\/Wake` - Pacific\/Wake\n\* `Pacific\/Wallis` - Pacific\/Wallis\n\* `Pacific\/Yap` - Pacific\/Yap\n\* `Poland` - Poland\n\* `Portugal` - Portugal\n\* `ROC` - ROC\n\* `ROK` - ROK\n\* `Singapore` - Singapore\n\* `Turkey` - Turkey\n\* `UCT` - UCT\n\* `US\/Alaska` - US\/Alaska\n\* `US\/Aleutian` - US\/Aleutian\n\* `US\/Arizona` - US\/Arizona\n\* `US\/Central` - US\/Central\n\* `US\/East-Indiana` - US\/East-Indiana\n\* `US\/Eastern` - US\/Eastern\n\* `US\/Hawaii` - US\/Hawaii\n\* `US\/Indiana-Starke` - US\/Indiana-Starke\n\* `US\/Michigan` - US\/Michigan\n\* `US\/Mountain` - US\/Mountain\n\* `US\/Pacific` - US\/Pacific\n\* `US\/Samoa` - US\/Samoa\n\* `UTC` - UTC\n\* `Universal` - Universal\n\* `W-SU` - W-SU\n\* `WET` - WET\n\* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(
                zod
                    .string()
                    .max(
                        organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyPersonDisplayNamePropertiesItemMax
                    )
            )
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat(
                'decimal',
                organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodySessionRecordingSampleRateRegExp
            )
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(
                organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin
            )
            .max(
                organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax
            )
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('\* `0` - Sunday\n\* `1` - Monday'),
                zod.null(),
            ])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n\* `0` - Sunday\n\* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyRecordingDomainsItemMax)
                    .nullable()
            )
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations \/ live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(
                        organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax
                    )
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyDefaultDataThemeMin)
            .max(organizationsProjectsDeleteSecretTokenBackupPartialUpdateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Manage experiment configuration for this project.
 */
export const organizationsProjectsExperimentsConfigPartialUpdateBodyNameMax = 200

export const organizationsProjectsExperimentsConfigPartialUpdateBodyProductDescriptionMax = 1000

export const organizationsProjectsExperimentsConfigPartialUpdateBodyAppUrlsItemMax = 200

export const organizationsProjectsExperimentsConfigPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsExperimentsConfigPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const organizationsProjectsExperimentsConfigPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsExperimentsConfigPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsExperimentsConfigPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsExperimentsConfigPartialUpdateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsExperimentsConfigPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsExperimentsConfigPartialUpdateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsExperimentsConfigPartialUpdateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsExperimentsConfigPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsExperimentsConfigPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsExperimentsConfigPartialUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(zod.string().max(organizationsProjectsExperimentsConfigPartialUpdateBodyAppUrlsItemMax).nullable())
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal\/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal\/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America\/Los_Angeles`).\n\n\* `Africa\/Abidjan` - Africa\/Abidjan\n\* `Africa\/Accra` - Africa\/Accra\n\* `Africa\/Addis_Ababa` - Africa\/Addis_Ababa\n\* `Africa\/Algiers` - Africa\/Algiers\n\* `Africa\/Asmara` - Africa\/Asmara\n\* `Africa\/Asmera` - Africa\/Asmera\n\* `Africa\/Bamako` - Africa\/Bamako\n\* `Africa\/Bangui` - Africa\/Bangui\n\* `Africa\/Banjul` - Africa\/Banjul\n\* `Africa\/Bissau` - Africa\/Bissau\n\* `Africa\/Blantyre` - Africa\/Blantyre\n\* `Africa\/Brazzaville` - Africa\/Brazzaville\n\* `Africa\/Bujumbura` - Africa\/Bujumbura\n\* `Africa\/Cairo` - Africa\/Cairo\n\* `Africa\/Casablanca` - Africa\/Casablanca\n\* `Africa\/Ceuta` - Africa\/Ceuta\n\* `Africa\/Conakry` - Africa\/Conakry\n\* `Africa\/Dakar` - Africa\/Dakar\n\* `Africa\/Dar_es_Salaam` - Africa\/Dar_es_Salaam\n\* `Africa\/Djibouti` - Africa\/Djibouti\n\* `Africa\/Douala` - Africa\/Douala\n\* `Africa\/El_Aaiun` - Africa\/El_Aaiun\n\* `Africa\/Freetown` - Africa\/Freetown\n\* `Africa\/Gaborone` - Africa\/Gaborone\n\* `Africa\/Harare` - Africa\/Harare\n\* `Africa\/Johannesburg` - Africa\/Johannesburg\n\* `Africa\/Juba` - Africa\/Juba\n\* `Africa\/Kampala` - Africa\/Kampala\n\* `Africa\/Khartoum` - Africa\/Khartoum\n\* `Africa\/Kigali` - Africa\/Kigali\n\* `Africa\/Kinshasa` - Africa\/Kinshasa\n\* `Africa\/Lagos` - Africa\/Lagos\n\* `Africa\/Libreville` - Africa\/Libreville\n\* `Africa\/Lome` - Africa\/Lome\n\* `Africa\/Luanda` - Africa\/Luanda\n\* `Africa\/Lubumbashi` - Africa\/Lubumbashi\n\* `Africa\/Lusaka` - Africa\/Lusaka\n\* `Africa\/Malabo` - Africa\/Malabo\n\* `Africa\/Maputo` - Africa\/Maputo\n\* `Africa\/Maseru` - Africa\/Maseru\n\* `Africa\/Mbabane` - Africa\/Mbabane\n\* `Africa\/Mogadishu` - Africa\/Mogadishu\n\* `Africa\/Monrovia` - Africa\/Monrovia\n\* `Africa\/Nairobi` - Africa\/Nairobi\n\* `Africa\/Ndjamena` - Africa\/Ndjamena\n\* `Africa\/Niamey` - Africa\/Niamey\n\* `Africa\/Nouakchott` - Africa\/Nouakchott\n\* `Africa\/Ouagadougou` - Africa\/Ouagadougou\n\* `Africa\/Porto-Novo` - Africa\/Porto-Novo\n\* `Africa\/Sao_Tome` - Africa\/Sao_Tome\n\* `Africa\/Timbuktu` - Africa\/Timbuktu\n\* `Africa\/Tripoli` - Africa\/Tripoli\n\* `Africa\/Tunis` - Africa\/Tunis\n\* `Africa\/Windhoek` - Africa\/Windhoek\n\* `America\/Adak` - America\/Adak\n\* `America\/Anchorage` - America\/Anchorage\n\* `America\/Anguilla` - America\/Anguilla\n\* `America\/Antigua` - America\/Antigua\n\* `America\/Araguaina` - America\/Araguaina\n\* `America\/Argentina\/Buenos_Aires` - America\/Argentina\/Buenos_Aires\n\* `America\/Argentina\/Catamarca` - America\/Argentina\/Catamarca\n\* `America\/Argentina\/ComodRivadavia` - America\/Argentina\/ComodRivadavia\n\* `America\/Argentina\/Cordoba` - America\/Argentina\/Cordoba\n\* `America\/Argentina\/Jujuy` - America\/Argentina\/Jujuy\n\* `America\/Argentina\/La_Rioja` - America\/Argentina\/La_Rioja\n\* `America\/Argentina\/Mendoza` - America\/Argentina\/Mendoza\n\* `America\/Argentina\/Rio_Gallegos` - America\/Argentina\/Rio_Gallegos\n\* `America\/Argentina\/Salta` - America\/Argentina\/Salta\n\* `America\/Argentina\/San_Juan` - America\/Argentina\/San_Juan\n\* `America\/Argentina\/San_Luis` - America\/Argentina\/San_Luis\n\* `America\/Argentina\/Tucuman` - America\/Argentina\/Tucuman\n\* `America\/Argentina\/Ushuaia` - America\/Argentina\/Ushuaia\n\* `America\/Aruba` - America\/Aruba\n\* `America\/Asuncion` - America\/Asuncion\n\* `America\/Atikokan` - America\/Atikokan\n\* `America\/Atka` - America\/Atka\n\* `America\/Bahia` - America\/Bahia\n\* `America\/Bahia_Banderas` - America\/Bahia_Banderas\n\* `America\/Barbados` - America\/Barbados\n\* `America\/Belem` - America\/Belem\n\* `America\/Belize` - America\/Belize\n\* `America\/Blanc-Sablon` - America\/Blanc-Sablon\n\* `America\/Boa_Vista` - America\/Boa_Vista\n\* `America\/Bogota` - America\/Bogota\n\* `America\/Boise` - America\/Boise\n\* `America\/Buenos_Aires` - America\/Buenos_Aires\n\* `America\/Cambridge_Bay` - America\/Cambridge_Bay\n\* `America\/Campo_Grande` - America\/Campo_Grande\n\* `America\/Cancun` - America\/Cancun\n\* `America\/Caracas` - America\/Caracas\n\* `America\/Catamarca` - America\/Catamarca\n\* `America\/Cayenne` - America\/Cayenne\n\* `America\/Cayman` - America\/Cayman\n\* `America\/Chicago` - America\/Chicago\n\* `America\/Chihuahua` - America\/Chihuahua\n\* `America\/Ciudad_Juarez` - America\/Ciudad_Juarez\n\* `America\/Coral_Harbour` - America\/Coral_Harbour\n\* `America\/Cordoba` - America\/Cordoba\n\* `America\/Costa_Rica` - America\/Costa_Rica\n\* `America\/Creston` - America\/Creston\n\* `America\/Cuiaba` - America\/Cuiaba\n\* `America\/Curacao` - America\/Curacao\n\* `America\/Danmarkshavn` - America\/Danmarkshavn\n\* `America\/Dawson` - America\/Dawson\n\* `America\/Dawson_Creek` - America\/Dawson_Creek\n\* `America\/Denver` - America\/Denver\n\* `America\/Detroit` - America\/Detroit\n\* `America\/Dominica` - America\/Dominica\n\* `America\/Edmonton` - America\/Edmonton\n\* `America\/Eirunepe` - America\/Eirunepe\n\* `America\/El_Salvador` - America\/El_Salvador\n\* `America\/Ensenada` - America\/Ensenada\n\* `America\/Fort_Nelson` - America\/Fort_Nelson\n\* `America\/Fort_Wayne` - America\/Fort_Wayne\n\* `America\/Fortaleza` - America\/Fortaleza\n\* `America\/Glace_Bay` - America\/Glace_Bay\n\* `America\/Godthab` - America\/Godthab\n\* `America\/Goose_Bay` - America\/Goose_Bay\n\* `America\/Grand_Turk` - America\/Grand_Turk\n\* `America\/Grenada` - America\/Grenada\n\* `America\/Guadeloupe` - America\/Guadeloupe\n\* `America\/Guatemala` - America\/Guatemala\n\* `America\/Guayaquil` - America\/Guayaquil\n\* `America\/Guyana` - America\/Guyana\n\* `America\/Halifax` - America\/Halifax\n\* `America\/Havana` - America\/Havana\n\* `America\/Hermosillo` - America\/Hermosillo\n\* `America\/Indiana\/Indianapolis` - America\/Indiana\/Indianapolis\n\* `America\/Indiana\/Knox` - America\/Indiana\/Knox\n\* `America\/Indiana\/Marengo` - America\/Indiana\/Marengo\n\* `America\/Indiana\/Petersburg` - America\/Indiana\/Petersburg\n\* `America\/Indiana\/Tell_City` - America\/Indiana\/Tell_City\n\* `America\/Indiana\/Vevay` - America\/Indiana\/Vevay\n\* `America\/Indiana\/Vincennes` - America\/Indiana\/Vincennes\n\* `America\/Indiana\/Winamac` - America\/Indiana\/Winamac\n\* `America\/Indianapolis` - America\/Indianapolis\n\* `America\/Inuvik` - America\/Inuvik\n\* `America\/Iqaluit` - America\/Iqaluit\n\* `America\/Jamaica` - America\/Jamaica\n\* `America\/Jujuy` - America\/Jujuy\n\* `America\/Juneau` - America\/Juneau\n\* `America\/Kentucky\/Louisville` - America\/Kentucky\/Louisville\n\* `America\/Kentucky\/Monticello` - America\/Kentucky\/Monticello\n\* `America\/Knox_IN` - America\/Knox_IN\n\* `America\/Kralendijk` - America\/Kralendijk\n\* `America\/La_Paz` - America\/La_Paz\n\* `America\/Lima` - America\/Lima\n\* `America\/Los_Angeles` - America\/Los_Angeles\n\* `America\/Louisville` - America\/Louisville\n\* `America\/Lower_Princes` - America\/Lower_Princes\n\* `America\/Maceio` - America\/Maceio\n\* `America\/Managua` - America\/Managua\n\* `America\/Manaus` - America\/Manaus\n\* `America\/Marigot` - America\/Marigot\n\* `America\/Martinique` - America\/Martinique\n\* `America\/Matamoros` - America\/Matamoros\n\* `America\/Mazatlan` - America\/Mazatlan\n\* `America\/Mendoza` - America\/Mendoza\n\* `America\/Menominee` - America\/Menominee\n\* `America\/Merida` - America\/Merida\n\* `America\/Metlakatla` - America\/Metlakatla\n\* `America\/Mexico_City` - America\/Mexico_City\n\* `America\/Miquelon` - America\/Miquelon\n\* `America\/Moncton` - America\/Moncton\n\* `America\/Monterrey` - America\/Monterrey\n\* `America\/Montevideo` - America\/Montevideo\n\* `America\/Montreal` - America\/Montreal\n\* `America\/Montserrat` - America\/Montserrat\n\* `America\/Nassau` - America\/Nassau\n\* `America\/New_York` - America\/New_York\n\* `America\/Nipigon` - America\/Nipigon\n\* `America\/Nome` - America\/Nome\n\* `America\/Noronha` - America\/Noronha\n\* `America\/North_Dakota\/Beulah` - America\/North_Dakota\/Beulah\n\* `America\/North_Dakota\/Center` - America\/North_Dakota\/Center\n\* `America\/North_Dakota\/New_Salem` - America\/North_Dakota\/New_Salem\n\* `America\/Nuuk` - America\/Nuuk\n\* `America\/Ojinaga` - America\/Ojinaga\n\* `America\/Panama` - America\/Panama\n\* `America\/Pangnirtung` - America\/Pangnirtung\n\* `America\/Paramaribo` - America\/Paramaribo\n\* `America\/Phoenix` - America\/Phoenix\n\* `America\/Port-au-Prince` - America\/Port-au-Prince\n\* `America\/Port_of_Spain` - America\/Port_of_Spain\n\* `America\/Porto_Acre` - America\/Porto_Acre\n\* `America\/Porto_Velho` - America\/Porto_Velho\n\* `America\/Puerto_Rico` - America\/Puerto_Rico\n\* `America\/Punta_Arenas` - America\/Punta_Arenas\n\* `America\/Rainy_River` - America\/Rainy_River\n\* `America\/Rankin_Inlet` - America\/Rankin_Inlet\n\* `America\/Recife` - America\/Recife\n\* `America\/Regina` - America\/Regina\n\* `America\/Resolute` - America\/Resolute\n\* `America\/Rio_Branco` - America\/Rio_Branco\n\* `America\/Rosario` - America\/Rosario\n\* `America\/Santa_Isabel` - America\/Santa_Isabel\n\* `America\/Santarem` - America\/Santarem\n\* `America\/Santiago` - America\/Santiago\n\* `America\/Santo_Domingo` - America\/Santo_Domingo\n\* `America\/Sao_Paulo` - America\/Sao_Paulo\n\* `America\/Scoresbysund` - America\/Scoresbysund\n\* `America\/Shiprock` - America\/Shiprock\n\* `America\/Sitka` - America\/Sitka\n\* `America\/St_Barthelemy` - America\/St_Barthelemy\n\* `America\/St_Johns` - America\/St_Johns\n\* `America\/St_Kitts` - America\/St_Kitts\n\* `America\/St_Lucia` - America\/St_Lucia\n\* `America\/St_Thomas` - America\/St_Thomas\n\* `America\/St_Vincent` - America\/St_Vincent\n\* `America\/Swift_Current` - America\/Swift_Current\n\* `America\/Tegucigalpa` - America\/Tegucigalpa\n\* `America\/Thule` - America\/Thule\n\* `America\/Thunder_Bay` - America\/Thunder_Bay\n\* `America\/Tijuana` - America\/Tijuana\n\* `America\/Toronto` - America\/Toronto\n\* `America\/Tortola` - America\/Tortola\n\* `America\/Vancouver` - America\/Vancouver\n\* `America\/Virgin` - America\/Virgin\n\* `America\/Whitehorse` - America\/Whitehorse\n\* `America\/Winnipeg` - America\/Winnipeg\n\* `America\/Yakutat` - America\/Yakutat\n\* `America\/Yellowknife` - America\/Yellowknife\n\* `Antarctica\/Casey` - Antarctica\/Casey\n\* `Antarctica\/Davis` - Antarctica\/Davis\n\* `Antarctica\/DumontDUrville` - Antarctica\/DumontDUrville\n\* `Antarctica\/Macquarie` - Antarctica\/Macquarie\n\* `Antarctica\/Mawson` - Antarctica\/Mawson\n\* `Antarctica\/McMurdo` - Antarctica\/McMurdo\n\* `Antarctica\/Palmer` - Antarctica\/Palmer\n\* `Antarctica\/Rothera` - Antarctica\/Rothera\n\* `Antarctica\/South_Pole` - Antarctica\/South_Pole\n\* `Antarctica\/Syowa` - Antarctica\/Syowa\n\* `Antarctica\/Troll` - Antarctica\/Troll\n\* `Antarctica\/Vostok` - Antarctica\/Vostok\n\* `Arctic\/Longyearbyen` - Arctic\/Longyearbyen\n\* `Asia\/Aden` - Asia\/Aden\n\* `Asia\/Almaty` - Asia\/Almaty\n\* `Asia\/Amman` - Asia\/Amman\n\* `Asia\/Anadyr` - Asia\/Anadyr\n\* `Asia\/Aqtau` - Asia\/Aqtau\n\* `Asia\/Aqtobe` - Asia\/Aqtobe\n\* `Asia\/Ashgabat` - Asia\/Ashgabat\n\* `Asia\/Ashkhabad` - Asia\/Ashkhabad\n\* `Asia\/Atyrau` - Asia\/Atyrau\n\* `Asia\/Baghdad` - Asia\/Baghdad\n\* `Asia\/Bahrain` - Asia\/Bahrain\n\* `Asia\/Baku` - Asia\/Baku\n\* `Asia\/Bangkok` - Asia\/Bangkok\n\* `Asia\/Barnaul` - Asia\/Barnaul\n\* `Asia\/Beirut` - Asia\/Beirut\n\* `Asia\/Bishkek` - Asia\/Bishkek\n\* `Asia\/Brunei` - Asia\/Brunei\n\* `Asia\/Calcutta` - Asia\/Calcutta\n\* `Asia\/Chita` - Asia\/Chita\n\* `Asia\/Choibalsan` - Asia\/Choibalsan\n\* `Asia\/Chongqing` - Asia\/Chongqing\n\* `Asia\/Chungking` - Asia\/Chungking\n\* `Asia\/Colombo` - Asia\/Colombo\n\* `Asia\/Dacca` - Asia\/Dacca\n\* `Asia\/Damascus` - Asia\/Damascus\n\* `Asia\/Dhaka` - Asia\/Dhaka\n\* `Asia\/Dili` - Asia\/Dili\n\* `Asia\/Dubai` - Asia\/Dubai\n\* `Asia\/Dushanbe` - Asia\/Dushanbe\n\* `Asia\/Famagusta` - Asia\/Famagusta\n\* `Asia\/Gaza` - Asia\/Gaza\n\* `Asia\/Harbin` - Asia\/Harbin\n\* `Asia\/Hebron` - Asia\/Hebron\n\* `Asia\/Ho_Chi_Minh` - Asia\/Ho_Chi_Minh\n\* `Asia\/Hong_Kong` - Asia\/Hong_Kong\n\* `Asia\/Hovd` - Asia\/Hovd\n\* `Asia\/Irkutsk` - Asia\/Irkutsk\n\* `Asia\/Istanbul` - Asia\/Istanbul\n\* `Asia\/Jakarta` - Asia\/Jakarta\n\* `Asia\/Jayapura` - Asia\/Jayapura\n\* `Asia\/Jerusalem` - Asia\/Jerusalem\n\* `Asia\/Kabul` - Asia\/Kabul\n\* `Asia\/Kamchatka` - Asia\/Kamchatka\n\* `Asia\/Karachi` - Asia\/Karachi\n\* `Asia\/Kashgar` - Asia\/Kashgar\n\* `Asia\/Kathmandu` - Asia\/Kathmandu\n\* `Asia\/Katmandu` - Asia\/Katmandu\n\* `Asia\/Khandyga` - Asia\/Khandyga\n\* `Asia\/Kolkata` - Asia\/Kolkata\n\* `Asia\/Krasnoyarsk` - Asia\/Krasnoyarsk\n\* `Asia\/Kuala_Lumpur` - Asia\/Kuala_Lumpur\n\* `Asia\/Kuching` - Asia\/Kuching\n\* `Asia\/Kuwait` - Asia\/Kuwait\n\* `Asia\/Macao` - Asia\/Macao\n\* `Asia\/Macau` - Asia\/Macau\n\* `Asia\/Magadan` - Asia\/Magadan\n\* `Asia\/Makassar` - Asia\/Makassar\n\* `Asia\/Manila` - Asia\/Manila\n\* `Asia\/Muscat` - Asia\/Muscat\n\* `Asia\/Nicosia` - Asia\/Nicosia\n\* `Asia\/Novokuznetsk` - Asia\/Novokuznetsk\n\* `Asia\/Novosibirsk` - Asia\/Novosibirsk\n\* `Asia\/Omsk` - Asia\/Omsk\n\* `Asia\/Oral` - Asia\/Oral\n\* `Asia\/Phnom_Penh` - Asia\/Phnom_Penh\n\* `Asia\/Pontianak` - Asia\/Pontianak\n\* `Asia\/Pyongyang` - Asia\/Pyongyang\n\* `Asia\/Qatar` - Asia\/Qatar\n\* `Asia\/Qostanay` - Asia\/Qostanay\n\* `Asia\/Qyzylorda` - Asia\/Qyzylorda\n\* `Asia\/Rangoon` - Asia\/Rangoon\n\* `Asia\/Riyadh` - Asia\/Riyadh\n\* `Asia\/Saigon` - Asia\/Saigon\n\* `Asia\/Sakhalin` - Asia\/Sakhalin\n\* `Asia\/Samarkand` - Asia\/Samarkand\n\* `Asia\/Seoul` - Asia\/Seoul\n\* `Asia\/Shanghai` - Asia\/Shanghai\n\* `Asia\/Singapore` - Asia\/Singapore\n\* `Asia\/Srednekolymsk` - Asia\/Srednekolymsk\n\* `Asia\/Taipei` - Asia\/Taipei\n\* `Asia\/Tashkent` - Asia\/Tashkent\n\* `Asia\/Tbilisi` - Asia\/Tbilisi\n\* `Asia\/Tehran` - Asia\/Tehran\n\* `Asia\/Tel_Aviv` - Asia\/Tel_Aviv\n\* `Asia\/Thimbu` - Asia\/Thimbu\n\* `Asia\/Thimphu` - Asia\/Thimphu\n\* `Asia\/Tokyo` - Asia\/Tokyo\n\* `Asia\/Tomsk` - Asia\/Tomsk\n\* `Asia\/Ujung_Pandang` - Asia\/Ujung_Pandang\n\* `Asia\/Ulaanbaatar` - Asia\/Ulaanbaatar\n\* `Asia\/Ulan_Bator` - Asia\/Ulan_Bator\n\* `Asia\/Urumqi` - Asia\/Urumqi\n\* `Asia\/Ust-Nera` - Asia\/Ust-Nera\n\* `Asia\/Vientiane` - Asia\/Vientiane\n\* `Asia\/Vladivostok` - Asia\/Vladivostok\n\* `Asia\/Yakutsk` - Asia\/Yakutsk\n\* `Asia\/Yangon` - Asia\/Yangon\n\* `Asia\/Yekaterinburg` - Asia\/Yekaterinburg\n\* `Asia\/Yerevan` - Asia\/Yerevan\n\* `Atlantic\/Azores` - Atlantic\/Azores\n\* `Atlantic\/Bermuda` - Atlantic\/Bermuda\n\* `Atlantic\/Canary` - Atlantic\/Canary\n\* `Atlantic\/Cape_Verde` - Atlantic\/Cape_Verde\n\* `Atlantic\/Faeroe` - Atlantic\/Faeroe\n\* `Atlantic\/Faroe` - Atlantic\/Faroe\n\* `Atlantic\/Jan_Mayen` - Atlantic\/Jan_Mayen\n\* `Atlantic\/Madeira` - Atlantic\/Madeira\n\* `Atlantic\/Reykjavik` - Atlantic\/Reykjavik\n\* `Atlantic\/South_Georgia` - Atlantic\/South_Georgia\n\* `Atlantic\/St_Helena` - Atlantic\/St_Helena\n\* `Atlantic\/Stanley` - Atlantic\/Stanley\n\* `Australia\/ACT` - Australia\/ACT\n\* `Australia\/Adelaide` - Australia\/Adelaide\n\* `Australia\/Brisbane` - Australia\/Brisbane\n\* `Australia\/Broken_Hill` - Australia\/Broken_Hill\n\* `Australia\/Canberra` - Australia\/Canberra\n\* `Australia\/Currie` - Australia\/Currie\n\* `Australia\/Darwin` - Australia\/Darwin\n\* `Australia\/Eucla` - Australia\/Eucla\n\* `Australia\/Hobart` - Australia\/Hobart\n\* `Australia\/LHI` - Australia\/LHI\n\* `Australia\/Lindeman` - Australia\/Lindeman\n\* `Australia\/Lord_Howe` - Australia\/Lord_Howe\n\* `Australia\/Melbourne` - Australia\/Melbourne\n\* `Australia\/NSW` - Australia\/NSW\n\* `Australia\/North` - Australia\/North\n\* `Australia\/Perth` - Australia\/Perth\n\* `Australia\/Queensland` - Australia\/Queensland\n\* `Australia\/South` - Australia\/South\n\* `Australia\/Sydney` - Australia\/Sydney\n\* `Australia\/Tasmania` - Australia\/Tasmania\n\* `Australia\/Victoria` - Australia\/Victoria\n\* `Australia\/West` - Australia\/West\n\* `Australia\/Yancowinna` - Australia\/Yancowinna\n\* `Brazil\/Acre` - Brazil\/Acre\n\* `Brazil\/DeNoronha` - Brazil\/DeNoronha\n\* `Brazil\/East` - Brazil\/East\n\* `Brazil\/West` - Brazil\/West\n\* `CET` - CET\n\* `CST6CDT` - CST6CDT\n\* `Canada\/Atlantic` - Canada\/Atlantic\n\* `Canada\/Central` - Canada\/Central\n\* `Canada\/Eastern` - Canada\/Eastern\n\* `Canada\/Mountain` - Canada\/Mountain\n\* `Canada\/Newfoundland` - Canada\/Newfoundland\n\* `Canada\/Pacific` - Canada\/Pacific\n\* `Canada\/Saskatchewan` - Canada\/Saskatchewan\n\* `Canada\/Yukon` - Canada\/Yukon\n\* `Chile\/Continental` - Chile\/Continental\n\* `Chile\/EasterIsland` - Chile\/EasterIsland\n\* `Cuba` - Cuba\n\* `EET` - EET\n\* `EST` - EST\n\* `EST5EDT` - EST5EDT\n\* `Egypt` - Egypt\n\* `Eire` - Eire\n\* `Etc\/GMT` - Etc\/GMT\n\* `Etc\/GMT+0` - Etc\/GMT+0\n\* `Etc\/GMT+1` - Etc\/GMT+1\n\* `Etc\/GMT+10` - Etc\/GMT+10\n\* `Etc\/GMT+11` - Etc\/GMT+11\n\* `Etc\/GMT+12` - Etc\/GMT+12\n\* `Etc\/GMT+2` - Etc\/GMT+2\n\* `Etc\/GMT+3` - Etc\/GMT+3\n\* `Etc\/GMT+4` - Etc\/GMT+4\n\* `Etc\/GMT+5` - Etc\/GMT+5\n\* `Etc\/GMT+6` - Etc\/GMT+6\n\* `Etc\/GMT+7` - Etc\/GMT+7\n\* `Etc\/GMT+8` - Etc\/GMT+8\n\* `Etc\/GMT+9` - Etc\/GMT+9\n\* `Etc\/GMT-0` - Etc\/GMT-0\n\* `Etc\/GMT-1` - Etc\/GMT-1\n\* `Etc\/GMT-10` - Etc\/GMT-10\n\* `Etc\/GMT-11` - Etc\/GMT-11\n\* `Etc\/GMT-12` - Etc\/GMT-12\n\* `Etc\/GMT-13` - Etc\/GMT-13\n\* `Etc\/GMT-14` - Etc\/GMT-14\n\* `Etc\/GMT-2` - Etc\/GMT-2\n\* `Etc\/GMT-3` - Etc\/GMT-3\n\* `Etc\/GMT-4` - Etc\/GMT-4\n\* `Etc\/GMT-5` - Etc\/GMT-5\n\* `Etc\/GMT-6` - Etc\/GMT-6\n\* `Etc\/GMT-7` - Etc\/GMT-7\n\* `Etc\/GMT-8` - Etc\/GMT-8\n\* `Etc\/GMT-9` - Etc\/GMT-9\n\* `Etc\/GMT0` - Etc\/GMT0\n\* `Etc\/Greenwich` - Etc\/Greenwich\n\* `Etc\/UCT` - Etc\/UCT\n\* `Etc\/UTC` - Etc\/UTC\n\* `Etc\/Universal` - Etc\/Universal\n\* `Etc\/Zulu` - Etc\/Zulu\n\* `Europe\/Amsterdam` - Europe\/Amsterdam\n\* `Europe\/Andorra` - Europe\/Andorra\n\* `Europe\/Astrakhan` - Europe\/Astrakhan\n\* `Europe\/Athens` - Europe\/Athens\n\* `Europe\/Belfast` - Europe\/Belfast\n\* `Europe\/Belgrade` - Europe\/Belgrade\n\* `Europe\/Berlin` - Europe\/Berlin\n\* `Europe\/Bratislava` - Europe\/Bratislava\n\* `Europe\/Brussels` - Europe\/Brussels\n\* `Europe\/Bucharest` - Europe\/Bucharest\n\* `Europe\/Budapest` - Europe\/Budapest\n\* `Europe\/Busingen` - Europe\/Busingen\n\* `Europe\/Chisinau` - Europe\/Chisinau\n\* `Europe\/Copenhagen` - Europe\/Copenhagen\n\* `Europe\/Dublin` - Europe\/Dublin\n\* `Europe\/Gibraltar` - Europe\/Gibraltar\n\* `Europe\/Guernsey` - Europe\/Guernsey\n\* `Europe\/Helsinki` - Europe\/Helsinki\n\* `Europe\/Isle_of_Man` - Europe\/Isle_of_Man\n\* `Europe\/Istanbul` - Europe\/Istanbul\n\* `Europe\/Jersey` - Europe\/Jersey\n\* `Europe\/Kaliningrad` - Europe\/Kaliningrad\n\* `Europe\/Kiev` - Europe\/Kiev\n\* `Europe\/Kirov` - Europe\/Kirov\n\* `Europe\/Kyiv` - Europe\/Kyiv\n\* `Europe\/Lisbon` - Europe\/Lisbon\n\* `Europe\/Ljubljana` - Europe\/Ljubljana\n\* `Europe\/London` - Europe\/London\n\* `Europe\/Luxembourg` - Europe\/Luxembourg\n\* `Europe\/Madrid` - Europe\/Madrid\n\* `Europe\/Malta` - Europe\/Malta\n\* `Europe\/Mariehamn` - Europe\/Mariehamn\n\* `Europe\/Minsk` - Europe\/Minsk\n\* `Europe\/Monaco` - Europe\/Monaco\n\* `Europe\/Moscow` - Europe\/Moscow\n\* `Europe\/Nicosia` - Europe\/Nicosia\n\* `Europe\/Oslo` - Europe\/Oslo\n\* `Europe\/Paris` - Europe\/Paris\n\* `Europe\/Podgorica` - Europe\/Podgorica\n\* `Europe\/Prague` - Europe\/Prague\n\* `Europe\/Riga` - Europe\/Riga\n\* `Europe\/Rome` - Europe\/Rome\n\* `Europe\/Samara` - Europe\/Samara\n\* `Europe\/San_Marino` - Europe\/San_Marino\n\* `Europe\/Sarajevo` - Europe\/Sarajevo\n\* `Europe\/Saratov` - Europe\/Saratov\n\* `Europe\/Simferopol` - Europe\/Simferopol\n\* `Europe\/Skopje` - Europe\/Skopje\n\* `Europe\/Sofia` - Europe\/Sofia\n\* `Europe\/Stockholm` - Europe\/Stockholm\n\* `Europe\/Tallinn` - Europe\/Tallinn\n\* `Europe\/Tirane` - Europe\/Tirane\n\* `Europe\/Tiraspol` - Europe\/Tiraspol\n\* `Europe\/Ulyanovsk` - Europe\/Ulyanovsk\n\* `Europe\/Uzhgorod` - Europe\/Uzhgorod\n\* `Europe\/Vaduz` - Europe\/Vaduz\n\* `Europe\/Vatican` - Europe\/Vatican\n\* `Europe\/Vienna` - Europe\/Vienna\n\* `Europe\/Vilnius` - Europe\/Vilnius\n\* `Europe\/Volgograd` - Europe\/Volgograd\n\* `Europe\/Warsaw` - Europe\/Warsaw\n\* `Europe\/Zagreb` - Europe\/Zagreb\n\* `Europe\/Zaporozhye` - Europe\/Zaporozhye\n\* `Europe\/Zurich` - Europe\/Zurich\n\* `GB` - GB\n\* `GB-Eire` - GB-Eire\n\* `GMT` - GMT\n\* `GMT+0` - GMT+0\n\* `GMT-0` - GMT-0\n\* `GMT0` - GMT0\n\* `Greenwich` - Greenwich\n\* `HST` - HST\n\* `Hongkong` - Hongkong\n\* `Iceland` - Iceland\n\* `Indian\/Antananarivo` - Indian\/Antananarivo\n\* `Indian\/Chagos` - Indian\/Chagos\n\* `Indian\/Christmas` - Indian\/Christmas\n\* `Indian\/Cocos` - Indian\/Cocos\n\* `Indian\/Comoro` - Indian\/Comoro\n\* `Indian\/Kerguelen` - Indian\/Kerguelen\n\* `Indian\/Mahe` - Indian\/Mahe\n\* `Indian\/Maldives` - Indian\/Maldives\n\* `Indian\/Mauritius` - Indian\/Mauritius\n\* `Indian\/Mayotte` - Indian\/Mayotte\n\* `Indian\/Reunion` - Indian\/Reunion\n\* `Iran` - Iran\n\* `Israel` - Israel\n\* `Jamaica` - Jamaica\n\* `Japan` - Japan\n\* `Kwajalein` - Kwajalein\n\* `Libya` - Libya\n\* `MET` - MET\n\* `MST` - MST\n\* `MST7MDT` - MST7MDT\n\* `Mexico\/BajaNorte` - Mexico\/BajaNorte\n\* `Mexico\/BajaSur` - Mexico\/BajaSur\n\* `Mexico\/General` - Mexico\/General\n\* `NZ` - NZ\n\* `NZ-CHAT` - NZ-CHAT\n\* `Navajo` - Navajo\n\* `PRC` - PRC\n\* `PST8PDT` - PST8PDT\n\* `Pacific\/Apia` - Pacific\/Apia\n\* `Pacific\/Auckland` - Pacific\/Auckland\n\* `Pacific\/Bougainville` - Pacific\/Bougainville\n\* `Pacific\/Chatham` - Pacific\/Chatham\n\* `Pacific\/Chuuk` - Pacific\/Chuuk\n\* `Pacific\/Easter` - Pacific\/Easter\n\* `Pacific\/Efate` - Pacific\/Efate\n\* `Pacific\/Enderbury` - Pacific\/Enderbury\n\* `Pacific\/Fakaofo` - Pacific\/Fakaofo\n\* `Pacific\/Fiji` - Pacific\/Fiji\n\* `Pacific\/Funafuti` - Pacific\/Funafuti\n\* `Pacific\/Galapagos` - Pacific\/Galapagos\n\* `Pacific\/Gambier` - Pacific\/Gambier\n\* `Pacific\/Guadalcanal` - Pacific\/Guadalcanal\n\* `Pacific\/Guam` - Pacific\/Guam\n\* `Pacific\/Honolulu` - Pacific\/Honolulu\n\* `Pacific\/Johnston` - Pacific\/Johnston\n\* `Pacific\/Kanton` - Pacific\/Kanton\n\* `Pacific\/Kiritimati` - Pacific\/Kiritimati\n\* `Pacific\/Kosrae` - Pacific\/Kosrae\n\* `Pacific\/Kwajalein` - Pacific\/Kwajalein\n\* `Pacific\/Majuro` - Pacific\/Majuro\n\* `Pacific\/Marquesas` - Pacific\/Marquesas\n\* `Pacific\/Midway` - Pacific\/Midway\n\* `Pacific\/Nauru` - Pacific\/Nauru\n\* `Pacific\/Niue` - Pacific\/Niue\n\* `Pacific\/Norfolk` - Pacific\/Norfolk\n\* `Pacific\/Noumea` - Pacific\/Noumea\n\* `Pacific\/Pago_Pago` - Pacific\/Pago_Pago\n\* `Pacific\/Palau` - Pacific\/Palau\n\* `Pacific\/Pitcairn` - Pacific\/Pitcairn\n\* `Pacific\/Pohnpei` - Pacific\/Pohnpei\n\* `Pacific\/Ponape` - Pacific\/Ponape\n\* `Pacific\/Port_Moresby` - Pacific\/Port_Moresby\n\* `Pacific\/Rarotonga` - Pacific\/Rarotonga\n\* `Pacific\/Saipan` - Pacific\/Saipan\n\* `Pacific\/Samoa` - Pacific\/Samoa\n\* `Pacific\/Tahiti` - Pacific\/Tahiti\n\* `Pacific\/Tarawa` - Pacific\/Tarawa\n\* `Pacific\/Tongatapu` - Pacific\/Tongatapu\n\* `Pacific\/Truk` - Pacific\/Truk\n\* `Pacific\/Wake` - Pacific\/Wake\n\* `Pacific\/Wallis` - Pacific\/Wallis\n\* `Pacific\/Yap` - Pacific\/Yap\n\* `Poland` - Poland\n\* `Portugal` - Portugal\n\* `ROC` - ROC\n\* `ROK` - ROK\n\* `Singapore` - Singapore\n\* `Turkey` - Turkey\n\* `UCT` - UCT\n\* `US\/Alaska` - US\/Alaska\n\* `US\/Aleutian` - US\/Aleutian\n\* `US\/Arizona` - US\/Arizona\n\* `US\/Central` - US\/Central\n\* `US\/East-Indiana` - US\/East-Indiana\n\* `US\/Eastern` - US\/Eastern\n\* `US\/Hawaii` - US\/Hawaii\n\* `US\/Indiana-Starke` - US\/Indiana-Starke\n\* `US\/Michigan` - US\/Michigan\n\* `US\/Mountain` - US\/Mountain\n\* `US\/Pacific` - US\/Pacific\n\* `US\/Samoa` - US\/Samoa\n\* `UTC` - UTC\n\* `Universal` - Universal\n\* `W-SU` - W-SU\n\* `WET` - WET\n\* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsExperimentsConfigPartialUpdateBodyPersonDisplayNamePropertiesItemMax)
            )
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat(
                'decimal',
                organizationsProjectsExperimentsConfigPartialUpdateBodySessionRecordingSampleRateRegExp
            )
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(organizationsProjectsExperimentsConfigPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(organizationsProjectsExperimentsConfigPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(organizationsProjectsExperimentsConfigPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('\* `0` - Sunday\n\* `1` - Monday'),
                zod.null(),
            ])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n\* `0` - Sunday\n\* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsExperimentsConfigPartialUpdateBodyRecordingDomainsItemMax)
                    .nullable()
            )
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations \/ live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(
                        organizationsProjectsExperimentsConfigPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax
                    )
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsExperimentsConfigPartialUpdateBodyDefaultDataThemeMin)
            .max(organizationsProjectsExperimentsConfigPartialUpdateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Projects for the current organization.
 */
export const organizationsProjectsGenerateConversationsPublicTokenCreateBodyNameMax = 200

export const organizationsProjectsGenerateConversationsPublicTokenCreateBodyProductDescriptionMax = 1000

export const organizationsProjectsGenerateConversationsPublicTokenCreateBodyAppUrlsItemMax = 200

export const organizationsProjectsGenerateConversationsPublicTokenCreateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsGenerateConversationsPublicTokenCreateBodySessionRecordingSampleRateRegExp =
    new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const organizationsProjectsGenerateConversationsPublicTokenCreateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsGenerateConversationsPublicTokenCreateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsGenerateConversationsPublicTokenCreateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsGenerateConversationsPublicTokenCreateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsGenerateConversationsPublicTokenCreateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsGenerateConversationsPublicTokenCreateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsGenerateConversationsPublicTokenCreateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsGenerateConversationsPublicTokenCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsGenerateConversationsPublicTokenCreateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsGenerateConversationsPublicTokenCreateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsGenerateConversationsPublicTokenCreateBodyAppUrlsItemMax)
                    .nullable()
            )
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal\/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal\/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America\/Los_Angeles`).\n\n\* `Africa\/Abidjan` - Africa\/Abidjan\n\* `Africa\/Accra` - Africa\/Accra\n\* `Africa\/Addis_Ababa` - Africa\/Addis_Ababa\n\* `Africa\/Algiers` - Africa\/Algiers\n\* `Africa\/Asmara` - Africa\/Asmara\n\* `Africa\/Asmera` - Africa\/Asmera\n\* `Africa\/Bamako` - Africa\/Bamako\n\* `Africa\/Bangui` - Africa\/Bangui\n\* `Africa\/Banjul` - Africa\/Banjul\n\* `Africa\/Bissau` - Africa\/Bissau\n\* `Africa\/Blantyre` - Africa\/Blantyre\n\* `Africa\/Brazzaville` - Africa\/Brazzaville\n\* `Africa\/Bujumbura` - Africa\/Bujumbura\n\* `Africa\/Cairo` - Africa\/Cairo\n\* `Africa\/Casablanca` - Africa\/Casablanca\n\* `Africa\/Ceuta` - Africa\/Ceuta\n\* `Africa\/Conakry` - Africa\/Conakry\n\* `Africa\/Dakar` - Africa\/Dakar\n\* `Africa\/Dar_es_Salaam` - Africa\/Dar_es_Salaam\n\* `Africa\/Djibouti` - Africa\/Djibouti\n\* `Africa\/Douala` - Africa\/Douala\n\* `Africa\/El_Aaiun` - Africa\/El_Aaiun\n\* `Africa\/Freetown` - Africa\/Freetown\n\* `Africa\/Gaborone` - Africa\/Gaborone\n\* `Africa\/Harare` - Africa\/Harare\n\* `Africa\/Johannesburg` - Africa\/Johannesburg\n\* `Africa\/Juba` - Africa\/Juba\n\* `Africa\/Kampala` - Africa\/Kampala\n\* `Africa\/Khartoum` - Africa\/Khartoum\n\* `Africa\/Kigali` - Africa\/Kigali\n\* `Africa\/Kinshasa` - Africa\/Kinshasa\n\* `Africa\/Lagos` - Africa\/Lagos\n\* `Africa\/Libreville` - Africa\/Libreville\n\* `Africa\/Lome` - Africa\/Lome\n\* `Africa\/Luanda` - Africa\/Luanda\n\* `Africa\/Lubumbashi` - Africa\/Lubumbashi\n\* `Africa\/Lusaka` - Africa\/Lusaka\n\* `Africa\/Malabo` - Africa\/Malabo\n\* `Africa\/Maputo` - Africa\/Maputo\n\* `Africa\/Maseru` - Africa\/Maseru\n\* `Africa\/Mbabane` - Africa\/Mbabane\n\* `Africa\/Mogadishu` - Africa\/Mogadishu\n\* `Africa\/Monrovia` - Africa\/Monrovia\n\* `Africa\/Nairobi` - Africa\/Nairobi\n\* `Africa\/Ndjamena` - Africa\/Ndjamena\n\* `Africa\/Niamey` - Africa\/Niamey\n\* `Africa\/Nouakchott` - Africa\/Nouakchott\n\* `Africa\/Ouagadougou` - Africa\/Ouagadougou\n\* `Africa\/Porto-Novo` - Africa\/Porto-Novo\n\* `Africa\/Sao_Tome` - Africa\/Sao_Tome\n\* `Africa\/Timbuktu` - Africa\/Timbuktu\n\* `Africa\/Tripoli` - Africa\/Tripoli\n\* `Africa\/Tunis` - Africa\/Tunis\n\* `Africa\/Windhoek` - Africa\/Windhoek\n\* `America\/Adak` - America\/Adak\n\* `America\/Anchorage` - America\/Anchorage\n\* `America\/Anguilla` - America\/Anguilla\n\* `America\/Antigua` - America\/Antigua\n\* `America\/Araguaina` - America\/Araguaina\n\* `America\/Argentina\/Buenos_Aires` - America\/Argentina\/Buenos_Aires\n\* `America\/Argentina\/Catamarca` - America\/Argentina\/Catamarca\n\* `America\/Argentina\/ComodRivadavia` - America\/Argentina\/ComodRivadavia\n\* `America\/Argentina\/Cordoba` - America\/Argentina\/Cordoba\n\* `America\/Argentina\/Jujuy` - America\/Argentina\/Jujuy\n\* `America\/Argentina\/La_Rioja` - America\/Argentina\/La_Rioja\n\* `America\/Argentina\/Mendoza` - America\/Argentina\/Mendoza\n\* `America\/Argentina\/Rio_Gallegos` - America\/Argentina\/Rio_Gallegos\n\* `America\/Argentina\/Salta` - America\/Argentina\/Salta\n\* `America\/Argentina\/San_Juan` - America\/Argentina\/San_Juan\n\* `America\/Argentina\/San_Luis` - America\/Argentina\/San_Luis\n\* `America\/Argentina\/Tucuman` - America\/Argentina\/Tucuman\n\* `America\/Argentina\/Ushuaia` - America\/Argentina\/Ushuaia\n\* `America\/Aruba` - America\/Aruba\n\* `America\/Asuncion` - America\/Asuncion\n\* `America\/Atikokan` - America\/Atikokan\n\* `America\/Atka` - America\/Atka\n\* `America\/Bahia` - America\/Bahia\n\* `America\/Bahia_Banderas` - America\/Bahia_Banderas\n\* `America\/Barbados` - America\/Barbados\n\* `America\/Belem` - America\/Belem\n\* `America\/Belize` - America\/Belize\n\* `America\/Blanc-Sablon` - America\/Blanc-Sablon\n\* `America\/Boa_Vista` - America\/Boa_Vista\n\* `America\/Bogota` - America\/Bogota\n\* `America\/Boise` - America\/Boise\n\* `America\/Buenos_Aires` - America\/Buenos_Aires\n\* `America\/Cambridge_Bay` - America\/Cambridge_Bay\n\* `America\/Campo_Grande` - America\/Campo_Grande\n\* `America\/Cancun` - America\/Cancun\n\* `America\/Caracas` - America\/Caracas\n\* `America\/Catamarca` - America\/Catamarca\n\* `America\/Cayenne` - America\/Cayenne\n\* `America\/Cayman` - America\/Cayman\n\* `America\/Chicago` - America\/Chicago\n\* `America\/Chihuahua` - America\/Chihuahua\n\* `America\/Ciudad_Juarez` - America\/Ciudad_Juarez\n\* `America\/Coral_Harbour` - America\/Coral_Harbour\n\* `America\/Cordoba` - America\/Cordoba\n\* `America\/Costa_Rica` - America\/Costa_Rica\n\* `America\/Creston` - America\/Creston\n\* `America\/Cuiaba` - America\/Cuiaba\n\* `America\/Curacao` - America\/Curacao\n\* `America\/Danmarkshavn` - America\/Danmarkshavn\n\* `America\/Dawson` - America\/Dawson\n\* `America\/Dawson_Creek` - America\/Dawson_Creek\n\* `America\/Denver` - America\/Denver\n\* `America\/Detroit` - America\/Detroit\n\* `America\/Dominica` - America\/Dominica\n\* `America\/Edmonton` - America\/Edmonton\n\* `America\/Eirunepe` - America\/Eirunepe\n\* `America\/El_Salvador` - America\/El_Salvador\n\* `America\/Ensenada` - America\/Ensenada\n\* `America\/Fort_Nelson` - America\/Fort_Nelson\n\* `America\/Fort_Wayne` - America\/Fort_Wayne\n\* `America\/Fortaleza` - America\/Fortaleza\n\* `America\/Glace_Bay` - America\/Glace_Bay\n\* `America\/Godthab` - America\/Godthab\n\* `America\/Goose_Bay` - America\/Goose_Bay\n\* `America\/Grand_Turk` - America\/Grand_Turk\n\* `America\/Grenada` - America\/Grenada\n\* `America\/Guadeloupe` - America\/Guadeloupe\n\* `America\/Guatemala` - America\/Guatemala\n\* `America\/Guayaquil` - America\/Guayaquil\n\* `America\/Guyana` - America\/Guyana\n\* `America\/Halifax` - America\/Halifax\n\* `America\/Havana` - America\/Havana\n\* `America\/Hermosillo` - America\/Hermosillo\n\* `America\/Indiana\/Indianapolis` - America\/Indiana\/Indianapolis\n\* `America\/Indiana\/Knox` - America\/Indiana\/Knox\n\* `America\/Indiana\/Marengo` - America\/Indiana\/Marengo\n\* `America\/Indiana\/Petersburg` - America\/Indiana\/Petersburg\n\* `America\/Indiana\/Tell_City` - America\/Indiana\/Tell_City\n\* `America\/Indiana\/Vevay` - America\/Indiana\/Vevay\n\* `America\/Indiana\/Vincennes` - America\/Indiana\/Vincennes\n\* `America\/Indiana\/Winamac` - America\/Indiana\/Winamac\n\* `America\/Indianapolis` - America\/Indianapolis\n\* `America\/Inuvik` - America\/Inuvik\n\* `America\/Iqaluit` - America\/Iqaluit\n\* `America\/Jamaica` - America\/Jamaica\n\* `America\/Jujuy` - America\/Jujuy\n\* `America\/Juneau` - America\/Juneau\n\* `America\/Kentucky\/Louisville` - America\/Kentucky\/Louisville\n\* `America\/Kentucky\/Monticello` - America\/Kentucky\/Monticello\n\* `America\/Knox_IN` - America\/Knox_IN\n\* `America\/Kralendijk` - America\/Kralendijk\n\* `America\/La_Paz` - America\/La_Paz\n\* `America\/Lima` - America\/Lima\n\* `America\/Los_Angeles` - America\/Los_Angeles\n\* `America\/Louisville` - America\/Louisville\n\* `America\/Lower_Princes` - America\/Lower_Princes\n\* `America\/Maceio` - America\/Maceio\n\* `America\/Managua` - America\/Managua\n\* `America\/Manaus` - America\/Manaus\n\* `America\/Marigot` - America\/Marigot\n\* `America\/Martinique` - America\/Martinique\n\* `America\/Matamoros` - America\/Matamoros\n\* `America\/Mazatlan` - America\/Mazatlan\n\* `America\/Mendoza` - America\/Mendoza\n\* `America\/Menominee` - America\/Menominee\n\* `America\/Merida` - America\/Merida\n\* `America\/Metlakatla` - America\/Metlakatla\n\* `America\/Mexico_City` - America\/Mexico_City\n\* `America\/Miquelon` - America\/Miquelon\n\* `America\/Moncton` - America\/Moncton\n\* `America\/Monterrey` - America\/Monterrey\n\* `America\/Montevideo` - America\/Montevideo\n\* `America\/Montreal` - America\/Montreal\n\* `America\/Montserrat` - America\/Montserrat\n\* `America\/Nassau` - America\/Nassau\n\* `America\/New_York` - America\/New_York\n\* `America\/Nipigon` - America\/Nipigon\n\* `America\/Nome` - America\/Nome\n\* `America\/Noronha` - America\/Noronha\n\* `America\/North_Dakota\/Beulah` - America\/North_Dakota\/Beulah\n\* `America\/North_Dakota\/Center` - America\/North_Dakota\/Center\n\* `America\/North_Dakota\/New_Salem` - America\/North_Dakota\/New_Salem\n\* `America\/Nuuk` - America\/Nuuk\n\* `America\/Ojinaga` - America\/Ojinaga\n\* `America\/Panama` - America\/Panama\n\* `America\/Pangnirtung` - America\/Pangnirtung\n\* `America\/Paramaribo` - America\/Paramaribo\n\* `America\/Phoenix` - America\/Phoenix\n\* `America\/Port-au-Prince` - America\/Port-au-Prince\n\* `America\/Port_of_Spain` - America\/Port_of_Spain\n\* `America\/Porto_Acre` - America\/Porto_Acre\n\* `America\/Porto_Velho` - America\/Porto_Velho\n\* `America\/Puerto_Rico` - America\/Puerto_Rico\n\* `America\/Punta_Arenas` - America\/Punta_Arenas\n\* `America\/Rainy_River` - America\/Rainy_River\n\* `America\/Rankin_Inlet` - America\/Rankin_Inlet\n\* `America\/Recife` - America\/Recife\n\* `America\/Regina` - America\/Regina\n\* `America\/Resolute` - America\/Resolute\n\* `America\/Rio_Branco` - America\/Rio_Branco\n\* `America\/Rosario` - America\/Rosario\n\* `America\/Santa_Isabel` - America\/Santa_Isabel\n\* `America\/Santarem` - America\/Santarem\n\* `America\/Santiago` - America\/Santiago\n\* `America\/Santo_Domingo` - America\/Santo_Domingo\n\* `America\/Sao_Paulo` - America\/Sao_Paulo\n\* `America\/Scoresbysund` - America\/Scoresbysund\n\* `America\/Shiprock` - America\/Shiprock\n\* `America\/Sitka` - America\/Sitka\n\* `America\/St_Barthelemy` - America\/St_Barthelemy\n\* `America\/St_Johns` - America\/St_Johns\n\* `America\/St_Kitts` - America\/St_Kitts\n\* `America\/St_Lucia` - America\/St_Lucia\n\* `America\/St_Thomas` - America\/St_Thomas\n\* `America\/St_Vincent` - America\/St_Vincent\n\* `America\/Swift_Current` - America\/Swift_Current\n\* `America\/Tegucigalpa` - America\/Tegucigalpa\n\* `America\/Thule` - America\/Thule\n\* `America\/Thunder_Bay` - America\/Thunder_Bay\n\* `America\/Tijuana` - America\/Tijuana\n\* `America\/Toronto` - America\/Toronto\n\* `America\/Tortola` - America\/Tortola\n\* `America\/Vancouver` - America\/Vancouver\n\* `America\/Virgin` - America\/Virgin\n\* `America\/Whitehorse` - America\/Whitehorse\n\* `America\/Winnipeg` - America\/Winnipeg\n\* `America\/Yakutat` - America\/Yakutat\n\* `America\/Yellowknife` - America\/Yellowknife\n\* `Antarctica\/Casey` - Antarctica\/Casey\n\* `Antarctica\/Davis` - Antarctica\/Davis\n\* `Antarctica\/DumontDUrville` - Antarctica\/DumontDUrville\n\* `Antarctica\/Macquarie` - Antarctica\/Macquarie\n\* `Antarctica\/Mawson` - Antarctica\/Mawson\n\* `Antarctica\/McMurdo` - Antarctica\/McMurdo\n\* `Antarctica\/Palmer` - Antarctica\/Palmer\n\* `Antarctica\/Rothera` - Antarctica\/Rothera\n\* `Antarctica\/South_Pole` - Antarctica\/South_Pole\n\* `Antarctica\/Syowa` - Antarctica\/Syowa\n\* `Antarctica\/Troll` - Antarctica\/Troll\n\* `Antarctica\/Vostok` - Antarctica\/Vostok\n\* `Arctic\/Longyearbyen` - Arctic\/Longyearbyen\n\* `Asia\/Aden` - Asia\/Aden\n\* `Asia\/Almaty` - Asia\/Almaty\n\* `Asia\/Amman` - Asia\/Amman\n\* `Asia\/Anadyr` - Asia\/Anadyr\n\* `Asia\/Aqtau` - Asia\/Aqtau\n\* `Asia\/Aqtobe` - Asia\/Aqtobe\n\* `Asia\/Ashgabat` - Asia\/Ashgabat\n\* `Asia\/Ashkhabad` - Asia\/Ashkhabad\n\* `Asia\/Atyrau` - Asia\/Atyrau\n\* `Asia\/Baghdad` - Asia\/Baghdad\n\* `Asia\/Bahrain` - Asia\/Bahrain\n\* `Asia\/Baku` - Asia\/Baku\n\* `Asia\/Bangkok` - Asia\/Bangkok\n\* `Asia\/Barnaul` - Asia\/Barnaul\n\* `Asia\/Beirut` - Asia\/Beirut\n\* `Asia\/Bishkek` - Asia\/Bishkek\n\* `Asia\/Brunei` - Asia\/Brunei\n\* `Asia\/Calcutta` - Asia\/Calcutta\n\* `Asia\/Chita` - Asia\/Chita\n\* `Asia\/Choibalsan` - Asia\/Choibalsan\n\* `Asia\/Chongqing` - Asia\/Chongqing\n\* `Asia\/Chungking` - Asia\/Chungking\n\* `Asia\/Colombo` - Asia\/Colombo\n\* `Asia\/Dacca` - Asia\/Dacca\n\* `Asia\/Damascus` - Asia\/Damascus\n\* `Asia\/Dhaka` - Asia\/Dhaka\n\* `Asia\/Dili` - Asia\/Dili\n\* `Asia\/Dubai` - Asia\/Dubai\n\* `Asia\/Dushanbe` - Asia\/Dushanbe\n\* `Asia\/Famagusta` - Asia\/Famagusta\n\* `Asia\/Gaza` - Asia\/Gaza\n\* `Asia\/Harbin` - Asia\/Harbin\n\* `Asia\/Hebron` - Asia\/Hebron\n\* `Asia\/Ho_Chi_Minh` - Asia\/Ho_Chi_Minh\n\* `Asia\/Hong_Kong` - Asia\/Hong_Kong\n\* `Asia\/Hovd` - Asia\/Hovd\n\* `Asia\/Irkutsk` - Asia\/Irkutsk\n\* `Asia\/Istanbul` - Asia\/Istanbul\n\* `Asia\/Jakarta` - Asia\/Jakarta\n\* `Asia\/Jayapura` - Asia\/Jayapura\n\* `Asia\/Jerusalem` - Asia\/Jerusalem\n\* `Asia\/Kabul` - Asia\/Kabul\n\* `Asia\/Kamchatka` - Asia\/Kamchatka\n\* `Asia\/Karachi` - Asia\/Karachi\n\* `Asia\/Kashgar` - Asia\/Kashgar\n\* `Asia\/Kathmandu` - Asia\/Kathmandu\n\* `Asia\/Katmandu` - Asia\/Katmandu\n\* `Asia\/Khandyga` - Asia\/Khandyga\n\* `Asia\/Kolkata` - Asia\/Kolkata\n\* `Asia\/Krasnoyarsk` - Asia\/Krasnoyarsk\n\* `Asia\/Kuala_Lumpur` - Asia\/Kuala_Lumpur\n\* `Asia\/Kuching` - Asia\/Kuching\n\* `Asia\/Kuwait` - Asia\/Kuwait\n\* `Asia\/Macao` - Asia\/Macao\n\* `Asia\/Macau` - Asia\/Macau\n\* `Asia\/Magadan` - Asia\/Magadan\n\* `Asia\/Makassar` - Asia\/Makassar\n\* `Asia\/Manila` - Asia\/Manila\n\* `Asia\/Muscat` - Asia\/Muscat\n\* `Asia\/Nicosia` - Asia\/Nicosia\n\* `Asia\/Novokuznetsk` - Asia\/Novokuznetsk\n\* `Asia\/Novosibirsk` - Asia\/Novosibirsk\n\* `Asia\/Omsk` - Asia\/Omsk\n\* `Asia\/Oral` - Asia\/Oral\n\* `Asia\/Phnom_Penh` - Asia\/Phnom_Penh\n\* `Asia\/Pontianak` - Asia\/Pontianak\n\* `Asia\/Pyongyang` - Asia\/Pyongyang\n\* `Asia\/Qatar` - Asia\/Qatar\n\* `Asia\/Qostanay` - Asia\/Qostanay\n\* `Asia\/Qyzylorda` - Asia\/Qyzylorda\n\* `Asia\/Rangoon` - Asia\/Rangoon\n\* `Asia\/Riyadh` - Asia\/Riyadh\n\* `Asia\/Saigon` - Asia\/Saigon\n\* `Asia\/Sakhalin` - Asia\/Sakhalin\n\* `Asia\/Samarkand` - Asia\/Samarkand\n\* `Asia\/Seoul` - Asia\/Seoul\n\* `Asia\/Shanghai` - Asia\/Shanghai\n\* `Asia\/Singapore` - Asia\/Singapore\n\* `Asia\/Srednekolymsk` - Asia\/Srednekolymsk\n\* `Asia\/Taipei` - Asia\/Taipei\n\* `Asia\/Tashkent` - Asia\/Tashkent\n\* `Asia\/Tbilisi` - Asia\/Tbilisi\n\* `Asia\/Tehran` - Asia\/Tehran\n\* `Asia\/Tel_Aviv` - Asia\/Tel_Aviv\n\* `Asia\/Thimbu` - Asia\/Thimbu\n\* `Asia\/Thimphu` - Asia\/Thimphu\n\* `Asia\/Tokyo` - Asia\/Tokyo\n\* `Asia\/Tomsk` - Asia\/Tomsk\n\* `Asia\/Ujung_Pandang` - Asia\/Ujung_Pandang\n\* `Asia\/Ulaanbaatar` - Asia\/Ulaanbaatar\n\* `Asia\/Ulan_Bator` - Asia\/Ulan_Bator\n\* `Asia\/Urumqi` - Asia\/Urumqi\n\* `Asia\/Ust-Nera` - Asia\/Ust-Nera\n\* `Asia\/Vientiane` - Asia\/Vientiane\n\* `Asia\/Vladivostok` - Asia\/Vladivostok\n\* `Asia\/Yakutsk` - Asia\/Yakutsk\n\* `Asia\/Yangon` - Asia\/Yangon\n\* `Asia\/Yekaterinburg` - Asia\/Yekaterinburg\n\* `Asia\/Yerevan` - Asia\/Yerevan\n\* `Atlantic\/Azores` - Atlantic\/Azores\n\* `Atlantic\/Bermuda` - Atlantic\/Bermuda\n\* `Atlantic\/Canary` - Atlantic\/Canary\n\* `Atlantic\/Cape_Verde` - Atlantic\/Cape_Verde\n\* `Atlantic\/Faeroe` - Atlantic\/Faeroe\n\* `Atlantic\/Faroe` - Atlantic\/Faroe\n\* `Atlantic\/Jan_Mayen` - Atlantic\/Jan_Mayen\n\* `Atlantic\/Madeira` - Atlantic\/Madeira\n\* `Atlantic\/Reykjavik` - Atlantic\/Reykjavik\n\* `Atlantic\/South_Georgia` - Atlantic\/South_Georgia\n\* `Atlantic\/St_Helena` - Atlantic\/St_Helena\n\* `Atlantic\/Stanley` - Atlantic\/Stanley\n\* `Australia\/ACT` - Australia\/ACT\n\* `Australia\/Adelaide` - Australia\/Adelaide\n\* `Australia\/Brisbane` - Australia\/Brisbane\n\* `Australia\/Broken_Hill` - Australia\/Broken_Hill\n\* `Australia\/Canberra` - Australia\/Canberra\n\* `Australia\/Currie` - Australia\/Currie\n\* `Australia\/Darwin` - Australia\/Darwin\n\* `Australia\/Eucla` - Australia\/Eucla\n\* `Australia\/Hobart` - Australia\/Hobart\n\* `Australia\/LHI` - Australia\/LHI\n\* `Australia\/Lindeman` - Australia\/Lindeman\n\* `Australia\/Lord_Howe` - Australia\/Lord_Howe\n\* `Australia\/Melbourne` - Australia\/Melbourne\n\* `Australia\/NSW` - Australia\/NSW\n\* `Australia\/North` - Australia\/North\n\* `Australia\/Perth` - Australia\/Perth\n\* `Australia\/Queensland` - Australia\/Queensland\n\* `Australia\/South` - Australia\/South\n\* `Australia\/Sydney` - Australia\/Sydney\n\* `Australia\/Tasmania` - Australia\/Tasmania\n\* `Australia\/Victoria` - Australia\/Victoria\n\* `Australia\/West` - Australia\/West\n\* `Australia\/Yancowinna` - Australia\/Yancowinna\n\* `Brazil\/Acre` - Brazil\/Acre\n\* `Brazil\/DeNoronha` - Brazil\/DeNoronha\n\* `Brazil\/East` - Brazil\/East\n\* `Brazil\/West` - Brazil\/West\n\* `CET` - CET\n\* `CST6CDT` - CST6CDT\n\* `Canada\/Atlantic` - Canada\/Atlantic\n\* `Canada\/Central` - Canada\/Central\n\* `Canada\/Eastern` - Canada\/Eastern\n\* `Canada\/Mountain` - Canada\/Mountain\n\* `Canada\/Newfoundland` - Canada\/Newfoundland\n\* `Canada\/Pacific` - Canada\/Pacific\n\* `Canada\/Saskatchewan` - Canada\/Saskatchewan\n\* `Canada\/Yukon` - Canada\/Yukon\n\* `Chile\/Continental` - Chile\/Continental\n\* `Chile\/EasterIsland` - Chile\/EasterIsland\n\* `Cuba` - Cuba\n\* `EET` - EET\n\* `EST` - EST\n\* `EST5EDT` - EST5EDT\n\* `Egypt` - Egypt\n\* `Eire` - Eire\n\* `Etc\/GMT` - Etc\/GMT\n\* `Etc\/GMT+0` - Etc\/GMT+0\n\* `Etc\/GMT+1` - Etc\/GMT+1\n\* `Etc\/GMT+10` - Etc\/GMT+10\n\* `Etc\/GMT+11` - Etc\/GMT+11\n\* `Etc\/GMT+12` - Etc\/GMT+12\n\* `Etc\/GMT+2` - Etc\/GMT+2\n\* `Etc\/GMT+3` - Etc\/GMT+3\n\* `Etc\/GMT+4` - Etc\/GMT+4\n\* `Etc\/GMT+5` - Etc\/GMT+5\n\* `Etc\/GMT+6` - Etc\/GMT+6\n\* `Etc\/GMT+7` - Etc\/GMT+7\n\* `Etc\/GMT+8` - Etc\/GMT+8\n\* `Etc\/GMT+9` - Etc\/GMT+9\n\* `Etc\/GMT-0` - Etc\/GMT-0\n\* `Etc\/GMT-1` - Etc\/GMT-1\n\* `Etc\/GMT-10` - Etc\/GMT-10\n\* `Etc\/GMT-11` - Etc\/GMT-11\n\* `Etc\/GMT-12` - Etc\/GMT-12\n\* `Etc\/GMT-13` - Etc\/GMT-13\n\* `Etc\/GMT-14` - Etc\/GMT-14\n\* `Etc\/GMT-2` - Etc\/GMT-2\n\* `Etc\/GMT-3` - Etc\/GMT-3\n\* `Etc\/GMT-4` - Etc\/GMT-4\n\* `Etc\/GMT-5` - Etc\/GMT-5\n\* `Etc\/GMT-6` - Etc\/GMT-6\n\* `Etc\/GMT-7` - Etc\/GMT-7\n\* `Etc\/GMT-8` - Etc\/GMT-8\n\* `Etc\/GMT-9` - Etc\/GMT-9\n\* `Etc\/GMT0` - Etc\/GMT0\n\* `Etc\/Greenwich` - Etc\/Greenwich\n\* `Etc\/UCT` - Etc\/UCT\n\* `Etc\/UTC` - Etc\/UTC\n\* `Etc\/Universal` - Etc\/Universal\n\* `Etc\/Zulu` - Etc\/Zulu\n\* `Europe\/Amsterdam` - Europe\/Amsterdam\n\* `Europe\/Andorra` - Europe\/Andorra\n\* `Europe\/Astrakhan` - Europe\/Astrakhan\n\* `Europe\/Athens` - Europe\/Athens\n\* `Europe\/Belfast` - Europe\/Belfast\n\* `Europe\/Belgrade` - Europe\/Belgrade\n\* `Europe\/Berlin` - Europe\/Berlin\n\* `Europe\/Bratislava` - Europe\/Bratislava\n\* `Europe\/Brussels` - Europe\/Brussels\n\* `Europe\/Bucharest` - Europe\/Bucharest\n\* `Europe\/Budapest` - Europe\/Budapest\n\* `Europe\/Busingen` - Europe\/Busingen\n\* `Europe\/Chisinau` - Europe\/Chisinau\n\* `Europe\/Copenhagen` - Europe\/Copenhagen\n\* `Europe\/Dublin` - Europe\/Dublin\n\* `Europe\/Gibraltar` - Europe\/Gibraltar\n\* `Europe\/Guernsey` - Europe\/Guernsey\n\* `Europe\/Helsinki` - Europe\/Helsinki\n\* `Europe\/Isle_of_Man` - Europe\/Isle_of_Man\n\* `Europe\/Istanbul` - Europe\/Istanbul\n\* `Europe\/Jersey` - Europe\/Jersey\n\* `Europe\/Kaliningrad` - Europe\/Kaliningrad\n\* `Europe\/Kiev` - Europe\/Kiev\n\* `Europe\/Kirov` - Europe\/Kirov\n\* `Europe\/Kyiv` - Europe\/Kyiv\n\* `Europe\/Lisbon` - Europe\/Lisbon\n\* `Europe\/Ljubljana` - Europe\/Ljubljana\n\* `Europe\/London` - Europe\/London\n\* `Europe\/Luxembourg` - Europe\/Luxembourg\n\* `Europe\/Madrid` - Europe\/Madrid\n\* `Europe\/Malta` - Europe\/Malta\n\* `Europe\/Mariehamn` - Europe\/Mariehamn\n\* `Europe\/Minsk` - Europe\/Minsk\n\* `Europe\/Monaco` - Europe\/Monaco\n\* `Europe\/Moscow` - Europe\/Moscow\n\* `Europe\/Nicosia` - Europe\/Nicosia\n\* `Europe\/Oslo` - Europe\/Oslo\n\* `Europe\/Paris` - Europe\/Paris\n\* `Europe\/Podgorica` - Europe\/Podgorica\n\* `Europe\/Prague` - Europe\/Prague\n\* `Europe\/Riga` - Europe\/Riga\n\* `Europe\/Rome` - Europe\/Rome\n\* `Europe\/Samara` - Europe\/Samara\n\* `Europe\/San_Marino` - Europe\/San_Marino\n\* `Europe\/Sarajevo` - Europe\/Sarajevo\n\* `Europe\/Saratov` - Europe\/Saratov\n\* `Europe\/Simferopol` - Europe\/Simferopol\n\* `Europe\/Skopje` - Europe\/Skopje\n\* `Europe\/Sofia` - Europe\/Sofia\n\* `Europe\/Stockholm` - Europe\/Stockholm\n\* `Europe\/Tallinn` - Europe\/Tallinn\n\* `Europe\/Tirane` - Europe\/Tirane\n\* `Europe\/Tiraspol` - Europe\/Tiraspol\n\* `Europe\/Ulyanovsk` - Europe\/Ulyanovsk\n\* `Europe\/Uzhgorod` - Europe\/Uzhgorod\n\* `Europe\/Vaduz` - Europe\/Vaduz\n\* `Europe\/Vatican` - Europe\/Vatican\n\* `Europe\/Vienna` - Europe\/Vienna\n\* `Europe\/Vilnius` - Europe\/Vilnius\n\* `Europe\/Volgograd` - Europe\/Volgograd\n\* `Europe\/Warsaw` - Europe\/Warsaw\n\* `Europe\/Zagreb` - Europe\/Zagreb\n\* `Europe\/Zaporozhye` - Europe\/Zaporozhye\n\* `Europe\/Zurich` - Europe\/Zurich\n\* `GB` - GB\n\* `GB-Eire` - GB-Eire\n\* `GMT` - GMT\n\* `GMT+0` - GMT+0\n\* `GMT-0` - GMT-0\n\* `GMT0` - GMT0\n\* `Greenwich` - Greenwich\n\* `HST` - HST\n\* `Hongkong` - Hongkong\n\* `Iceland` - Iceland\n\* `Indian\/Antananarivo` - Indian\/Antananarivo\n\* `Indian\/Chagos` - Indian\/Chagos\n\* `Indian\/Christmas` - Indian\/Christmas\n\* `Indian\/Cocos` - Indian\/Cocos\n\* `Indian\/Comoro` - Indian\/Comoro\n\* `Indian\/Kerguelen` - Indian\/Kerguelen\n\* `Indian\/Mahe` - Indian\/Mahe\n\* `Indian\/Maldives` - Indian\/Maldives\n\* `Indian\/Mauritius` - Indian\/Mauritius\n\* `Indian\/Mayotte` - Indian\/Mayotte\n\* `Indian\/Reunion` - Indian\/Reunion\n\* `Iran` - Iran\n\* `Israel` - Israel\n\* `Jamaica` - Jamaica\n\* `Japan` - Japan\n\* `Kwajalein` - Kwajalein\n\* `Libya` - Libya\n\* `MET` - MET\n\* `MST` - MST\n\* `MST7MDT` - MST7MDT\n\* `Mexico\/BajaNorte` - Mexico\/BajaNorte\n\* `Mexico\/BajaSur` - Mexico\/BajaSur\n\* `Mexico\/General` - Mexico\/General\n\* `NZ` - NZ\n\* `NZ-CHAT` - NZ-CHAT\n\* `Navajo` - Navajo\n\* `PRC` - PRC\n\* `PST8PDT` - PST8PDT\n\* `Pacific\/Apia` - Pacific\/Apia\n\* `Pacific\/Auckland` - Pacific\/Auckland\n\* `Pacific\/Bougainville` - Pacific\/Bougainville\n\* `Pacific\/Chatham` - Pacific\/Chatham\n\* `Pacific\/Chuuk` - Pacific\/Chuuk\n\* `Pacific\/Easter` - Pacific\/Easter\n\* `Pacific\/Efate` - Pacific\/Efate\n\* `Pacific\/Enderbury` - Pacific\/Enderbury\n\* `Pacific\/Fakaofo` - Pacific\/Fakaofo\n\* `Pacific\/Fiji` - Pacific\/Fiji\n\* `Pacific\/Funafuti` - Pacific\/Funafuti\n\* `Pacific\/Galapagos` - Pacific\/Galapagos\n\* `Pacific\/Gambier` - Pacific\/Gambier\n\* `Pacific\/Guadalcanal` - Pacific\/Guadalcanal\n\* `Pacific\/Guam` - Pacific\/Guam\n\* `Pacific\/Honolulu` - Pacific\/Honolulu\n\* `Pacific\/Johnston` - Pacific\/Johnston\n\* `Pacific\/Kanton` - Pacific\/Kanton\n\* `Pacific\/Kiritimati` - Pacific\/Kiritimati\n\* `Pacific\/Kosrae` - Pacific\/Kosrae\n\* `Pacific\/Kwajalein` - Pacific\/Kwajalein\n\* `Pacific\/Majuro` - Pacific\/Majuro\n\* `Pacific\/Marquesas` - Pacific\/Marquesas\n\* `Pacific\/Midway` - Pacific\/Midway\n\* `Pacific\/Nauru` - Pacific\/Nauru\n\* `Pacific\/Niue` - Pacific\/Niue\n\* `Pacific\/Norfolk` - Pacific\/Norfolk\n\* `Pacific\/Noumea` - Pacific\/Noumea\n\* `Pacific\/Pago_Pago` - Pacific\/Pago_Pago\n\* `Pacific\/Palau` - Pacific\/Palau\n\* `Pacific\/Pitcairn` - Pacific\/Pitcairn\n\* `Pacific\/Pohnpei` - Pacific\/Pohnpei\n\* `Pacific\/Ponape` - Pacific\/Ponape\n\* `Pacific\/Port_Moresby` - Pacific\/Port_Moresby\n\* `Pacific\/Rarotonga` - Pacific\/Rarotonga\n\* `Pacific\/Saipan` - Pacific\/Saipan\n\* `Pacific\/Samoa` - Pacific\/Samoa\n\* `Pacific\/Tahiti` - Pacific\/Tahiti\n\* `Pacific\/Tarawa` - Pacific\/Tarawa\n\* `Pacific\/Tongatapu` - Pacific\/Tongatapu\n\* `Pacific\/Truk` - Pacific\/Truk\n\* `Pacific\/Wake` - Pacific\/Wake\n\* `Pacific\/Wallis` - Pacific\/Wallis\n\* `Pacific\/Yap` - Pacific\/Yap\n\* `Poland` - Poland\n\* `Portugal` - Portugal\n\* `ROC` - ROC\n\* `ROK` - ROK\n\* `Singapore` - Singapore\n\* `Turkey` - Turkey\n\* `UCT` - UCT\n\* `US\/Alaska` - US\/Alaska\n\* `US\/Aleutian` - US\/Aleutian\n\* `US\/Arizona` - US\/Arizona\n\* `US\/Central` - US\/Central\n\* `US\/East-Indiana` - US\/East-Indiana\n\* `US\/Eastern` - US\/Eastern\n\* `US\/Hawaii` - US\/Hawaii\n\* `US\/Indiana-Starke` - US\/Indiana-Starke\n\* `US\/Michigan` - US\/Michigan\n\* `US\/Mountain` - US\/Mountain\n\* `US\/Pacific` - US\/Pacific\n\* `US\/Samoa` - US\/Samoa\n\* `UTC` - UTC\n\* `Universal` - Universal\n\* `W-SU` - W-SU\n\* `WET` - WET\n\* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(
                zod
                    .string()
                    .max(
                        organizationsProjectsGenerateConversationsPublicTokenCreateBodyPersonDisplayNamePropertiesItemMax
                    )
            )
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat(
                'decimal',
                organizationsProjectsGenerateConversationsPublicTokenCreateBodySessionRecordingSampleRateRegExp
            )
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(
                organizationsProjectsGenerateConversationsPublicTokenCreateBodySessionRecordingMinimumDurationMillisecondsMin
            )
            .max(
                organizationsProjectsGenerateConversationsPublicTokenCreateBodySessionRecordingMinimumDurationMillisecondsMax
            )
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(
                organizationsProjectsGenerateConversationsPublicTokenCreateBodySessionRecordingTriggerMatchTypeConfigMax
            )
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('\* `0` - Sunday\n\* `1` - Monday'),
                zod.null(),
            ])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n\* `0` - Sunday\n\* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsGenerateConversationsPublicTokenCreateBodyRecordingDomainsItemMax)
                    .nullable()
            )
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations \/ live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(
                        organizationsProjectsGenerateConversationsPublicTokenCreateBodyMarketingAnalyticsConfigAttributionWindowDaysMax
                    )
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsGenerateConversationsPublicTokenCreateBodyDefaultDataThemeMin)
            .max(organizationsProjectsGenerateConversationsPublicTokenCreateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Manage logs product configuration for this project's canonical environment.
 * Mirrors the env-router action so /api/projects/:id/logs_config/ resolves
 * alongside the legacy /api/environments/:id/logs_config/ alias.
 */
export const organizationsProjectsLogsConfigPartialUpdateBodyNameMax = 200

export const organizationsProjectsLogsConfigPartialUpdateBodyProductDescriptionMax = 1000

export const organizationsProjectsLogsConfigPartialUpdateBodyAppUrlsItemMax = 200

export const organizationsProjectsLogsConfigPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsLogsConfigPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const organizationsProjectsLogsConfigPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsLogsConfigPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsLogsConfigPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsLogsConfigPartialUpdateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsLogsConfigPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsLogsConfigPartialUpdateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsLogsConfigPartialUpdateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsLogsConfigPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsLogsConfigPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsLogsConfigPartialUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(zod.string().max(organizationsProjectsLogsConfigPartialUpdateBodyAppUrlsItemMax).nullable())
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal\/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal\/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America\/Los_Angeles`).\n\n\* `Africa\/Abidjan` - Africa\/Abidjan\n\* `Africa\/Accra` - Africa\/Accra\n\* `Africa\/Addis_Ababa` - Africa\/Addis_Ababa\n\* `Africa\/Algiers` - Africa\/Algiers\n\* `Africa\/Asmara` - Africa\/Asmara\n\* `Africa\/Asmera` - Africa\/Asmera\n\* `Africa\/Bamako` - Africa\/Bamako\n\* `Africa\/Bangui` - Africa\/Bangui\n\* `Africa\/Banjul` - Africa\/Banjul\n\* `Africa\/Bissau` - Africa\/Bissau\n\* `Africa\/Blantyre` - Africa\/Blantyre\n\* `Africa\/Brazzaville` - Africa\/Brazzaville\n\* `Africa\/Bujumbura` - Africa\/Bujumbura\n\* `Africa\/Cairo` - Africa\/Cairo\n\* `Africa\/Casablanca` - Africa\/Casablanca\n\* `Africa\/Ceuta` - Africa\/Ceuta\n\* `Africa\/Conakry` - Africa\/Conakry\n\* `Africa\/Dakar` - Africa\/Dakar\n\* `Africa\/Dar_es_Salaam` - Africa\/Dar_es_Salaam\n\* `Africa\/Djibouti` - Africa\/Djibouti\n\* `Africa\/Douala` - Africa\/Douala\n\* `Africa\/El_Aaiun` - Africa\/El_Aaiun\n\* `Africa\/Freetown` - Africa\/Freetown\n\* `Africa\/Gaborone` - Africa\/Gaborone\n\* `Africa\/Harare` - Africa\/Harare\n\* `Africa\/Johannesburg` - Africa\/Johannesburg\n\* `Africa\/Juba` - Africa\/Juba\n\* `Africa\/Kampala` - Africa\/Kampala\n\* `Africa\/Khartoum` - Africa\/Khartoum\n\* `Africa\/Kigali` - Africa\/Kigali\n\* `Africa\/Kinshasa` - Africa\/Kinshasa\n\* `Africa\/Lagos` - Africa\/Lagos\n\* `Africa\/Libreville` - Africa\/Libreville\n\* `Africa\/Lome` - Africa\/Lome\n\* `Africa\/Luanda` - Africa\/Luanda\n\* `Africa\/Lubumbashi` - Africa\/Lubumbashi\n\* `Africa\/Lusaka` - Africa\/Lusaka\n\* `Africa\/Malabo` - Africa\/Malabo\n\* `Africa\/Maputo` - Africa\/Maputo\n\* `Africa\/Maseru` - Africa\/Maseru\n\* `Africa\/Mbabane` - Africa\/Mbabane\n\* `Africa\/Mogadishu` - Africa\/Mogadishu\n\* `Africa\/Monrovia` - Africa\/Monrovia\n\* `Africa\/Nairobi` - Africa\/Nairobi\n\* `Africa\/Ndjamena` - Africa\/Ndjamena\n\* `Africa\/Niamey` - Africa\/Niamey\n\* `Africa\/Nouakchott` - Africa\/Nouakchott\n\* `Africa\/Ouagadougou` - Africa\/Ouagadougou\n\* `Africa\/Porto-Novo` - Africa\/Porto-Novo\n\* `Africa\/Sao_Tome` - Africa\/Sao_Tome\n\* `Africa\/Timbuktu` - Africa\/Timbuktu\n\* `Africa\/Tripoli` - Africa\/Tripoli\n\* `Africa\/Tunis` - Africa\/Tunis\n\* `Africa\/Windhoek` - Africa\/Windhoek\n\* `America\/Adak` - America\/Adak\n\* `America\/Anchorage` - America\/Anchorage\n\* `America\/Anguilla` - America\/Anguilla\n\* `America\/Antigua` - America\/Antigua\n\* `America\/Araguaina` - America\/Araguaina\n\* `America\/Argentina\/Buenos_Aires` - America\/Argentina\/Buenos_Aires\n\* `America\/Argentina\/Catamarca` - America\/Argentina\/Catamarca\n\* `America\/Argentina\/ComodRivadavia` - America\/Argentina\/ComodRivadavia\n\* `America\/Argentina\/Cordoba` - America\/Argentina\/Cordoba\n\* `America\/Argentina\/Jujuy` - America\/Argentina\/Jujuy\n\* `America\/Argentina\/La_Rioja` - America\/Argentina\/La_Rioja\n\* `America\/Argentina\/Mendoza` - America\/Argentina\/Mendoza\n\* `America\/Argentina\/Rio_Gallegos` - America\/Argentina\/Rio_Gallegos\n\* `America\/Argentina\/Salta` - America\/Argentina\/Salta\n\* `America\/Argentina\/San_Juan` - America\/Argentina\/San_Juan\n\* `America\/Argentina\/San_Luis` - America\/Argentina\/San_Luis\n\* `America\/Argentina\/Tucuman` - America\/Argentina\/Tucuman\n\* `America\/Argentina\/Ushuaia` - America\/Argentina\/Ushuaia\n\* `America\/Aruba` - America\/Aruba\n\* `America\/Asuncion` - America\/Asuncion\n\* `America\/Atikokan` - America\/Atikokan\n\* `America\/Atka` - America\/Atka\n\* `America\/Bahia` - America\/Bahia\n\* `America\/Bahia_Banderas` - America\/Bahia_Banderas\n\* `America\/Barbados` - America\/Barbados\n\* `America\/Belem` - America\/Belem\n\* `America\/Belize` - America\/Belize\n\* `America\/Blanc-Sablon` - America\/Blanc-Sablon\n\* `America\/Boa_Vista` - America\/Boa_Vista\n\* `America\/Bogota` - America\/Bogota\n\* `America\/Boise` - America\/Boise\n\* `America\/Buenos_Aires` - America\/Buenos_Aires\n\* `America\/Cambridge_Bay` - America\/Cambridge_Bay\n\* `America\/Campo_Grande` - America\/Campo_Grande\n\* `America\/Cancun` - America\/Cancun\n\* `America\/Caracas` - America\/Caracas\n\* `America\/Catamarca` - America\/Catamarca\n\* `America\/Cayenne` - America\/Cayenne\n\* `America\/Cayman` - America\/Cayman\n\* `America\/Chicago` - America\/Chicago\n\* `America\/Chihuahua` - America\/Chihuahua\n\* `America\/Ciudad_Juarez` - America\/Ciudad_Juarez\n\* `America\/Coral_Harbour` - America\/Coral_Harbour\n\* `America\/Cordoba` - America\/Cordoba\n\* `America\/Costa_Rica` - America\/Costa_Rica\n\* `America\/Creston` - America\/Creston\n\* `America\/Cuiaba` - America\/Cuiaba\n\* `America\/Curacao` - America\/Curacao\n\* `America\/Danmarkshavn` - America\/Danmarkshavn\n\* `America\/Dawson` - America\/Dawson\n\* `America\/Dawson_Creek` - America\/Dawson_Creek\n\* `America\/Denver` - America\/Denver\n\* `America\/Detroit` - America\/Detroit\n\* `America\/Dominica` - America\/Dominica\n\* `America\/Edmonton` - America\/Edmonton\n\* `America\/Eirunepe` - America\/Eirunepe\n\* `America\/El_Salvador` - America\/El_Salvador\n\* `America\/Ensenada` - America\/Ensenada\n\* `America\/Fort_Nelson` - America\/Fort_Nelson\n\* `America\/Fort_Wayne` - America\/Fort_Wayne\n\* `America\/Fortaleza` - America\/Fortaleza\n\* `America\/Glace_Bay` - America\/Glace_Bay\n\* `America\/Godthab` - America\/Godthab\n\* `America\/Goose_Bay` - America\/Goose_Bay\n\* `America\/Grand_Turk` - America\/Grand_Turk\n\* `America\/Grenada` - America\/Grenada\n\* `America\/Guadeloupe` - America\/Guadeloupe\n\* `America\/Guatemala` - America\/Guatemala\n\* `America\/Guayaquil` - America\/Guayaquil\n\* `America\/Guyana` - America\/Guyana\n\* `America\/Halifax` - America\/Halifax\n\* `America\/Havana` - America\/Havana\n\* `America\/Hermosillo` - America\/Hermosillo\n\* `America\/Indiana\/Indianapolis` - America\/Indiana\/Indianapolis\n\* `America\/Indiana\/Knox` - America\/Indiana\/Knox\n\* `America\/Indiana\/Marengo` - America\/Indiana\/Marengo\n\* `America\/Indiana\/Petersburg` - America\/Indiana\/Petersburg\n\* `America\/Indiana\/Tell_City` - America\/Indiana\/Tell_City\n\* `America\/Indiana\/Vevay` - America\/Indiana\/Vevay\n\* `America\/Indiana\/Vincennes` - America\/Indiana\/Vincennes\n\* `America\/Indiana\/Winamac` - America\/Indiana\/Winamac\n\* `America\/Indianapolis` - America\/Indianapolis\n\* `America\/Inuvik` - America\/Inuvik\n\* `America\/Iqaluit` - America\/Iqaluit\n\* `America\/Jamaica` - America\/Jamaica\n\* `America\/Jujuy` - America\/Jujuy\n\* `America\/Juneau` - America\/Juneau\n\* `America\/Kentucky\/Louisville` - America\/Kentucky\/Louisville\n\* `America\/Kentucky\/Monticello` - America\/Kentucky\/Monticello\n\* `America\/Knox_IN` - America\/Knox_IN\n\* `America\/Kralendijk` - America\/Kralendijk\n\* `America\/La_Paz` - America\/La_Paz\n\* `America\/Lima` - America\/Lima\n\* `America\/Los_Angeles` - America\/Los_Angeles\n\* `America\/Louisville` - America\/Louisville\n\* `America\/Lower_Princes` - America\/Lower_Princes\n\* `America\/Maceio` - America\/Maceio\n\* `America\/Managua` - America\/Managua\n\* `America\/Manaus` - America\/Manaus\n\* `America\/Marigot` - America\/Marigot\n\* `America\/Martinique` - America\/Martinique\n\* `America\/Matamoros` - America\/Matamoros\n\* `America\/Mazatlan` - America\/Mazatlan\n\* `America\/Mendoza` - America\/Mendoza\n\* `America\/Menominee` - America\/Menominee\n\* `America\/Merida` - America\/Merida\n\* `America\/Metlakatla` - America\/Metlakatla\n\* `America\/Mexico_City` - America\/Mexico_City\n\* `America\/Miquelon` - America\/Miquelon\n\* `America\/Moncton` - America\/Moncton\n\* `America\/Monterrey` - America\/Monterrey\n\* `America\/Montevideo` - America\/Montevideo\n\* `America\/Montreal` - America\/Montreal\n\* `America\/Montserrat` - America\/Montserrat\n\* `America\/Nassau` - America\/Nassau\n\* `America\/New_York` - America\/New_York\n\* `America\/Nipigon` - America\/Nipigon\n\* `America\/Nome` - America\/Nome\n\* `America\/Noronha` - America\/Noronha\n\* `America\/North_Dakota\/Beulah` - America\/North_Dakota\/Beulah\n\* `America\/North_Dakota\/Center` - America\/North_Dakota\/Center\n\* `America\/North_Dakota\/New_Salem` - America\/North_Dakota\/New_Salem\n\* `America\/Nuuk` - America\/Nuuk\n\* `America\/Ojinaga` - America\/Ojinaga\n\* `America\/Panama` - America\/Panama\n\* `America\/Pangnirtung` - America\/Pangnirtung\n\* `America\/Paramaribo` - America\/Paramaribo\n\* `America\/Phoenix` - America\/Phoenix\n\* `America\/Port-au-Prince` - America\/Port-au-Prince\n\* `America\/Port_of_Spain` - America\/Port_of_Spain\n\* `America\/Porto_Acre` - America\/Porto_Acre\n\* `America\/Porto_Velho` - America\/Porto_Velho\n\* `America\/Puerto_Rico` - America\/Puerto_Rico\n\* `America\/Punta_Arenas` - America\/Punta_Arenas\n\* `America\/Rainy_River` - America\/Rainy_River\n\* `America\/Rankin_Inlet` - America\/Rankin_Inlet\n\* `America\/Recife` - America\/Recife\n\* `America\/Regina` - America\/Regina\n\* `America\/Resolute` - America\/Resolute\n\* `America\/Rio_Branco` - America\/Rio_Branco\n\* `America\/Rosario` - America\/Rosario\n\* `America\/Santa_Isabel` - America\/Santa_Isabel\n\* `America\/Santarem` - America\/Santarem\n\* `America\/Santiago` - America\/Santiago\n\* `America\/Santo_Domingo` - America\/Santo_Domingo\n\* `America\/Sao_Paulo` - America\/Sao_Paulo\n\* `America\/Scoresbysund` - America\/Scoresbysund\n\* `America\/Shiprock` - America\/Shiprock\n\* `America\/Sitka` - America\/Sitka\n\* `America\/St_Barthelemy` - America\/St_Barthelemy\n\* `America\/St_Johns` - America\/St_Johns\n\* `America\/St_Kitts` - America\/St_Kitts\n\* `America\/St_Lucia` - America\/St_Lucia\n\* `America\/St_Thomas` - America\/St_Thomas\n\* `America\/St_Vincent` - America\/St_Vincent\n\* `America\/Swift_Current` - America\/Swift_Current\n\* `America\/Tegucigalpa` - America\/Tegucigalpa\n\* `America\/Thule` - America\/Thule\n\* `America\/Thunder_Bay` - America\/Thunder_Bay\n\* `America\/Tijuana` - America\/Tijuana\n\* `America\/Toronto` - America\/Toronto\n\* `America\/Tortola` - America\/Tortola\n\* `America\/Vancouver` - America\/Vancouver\n\* `America\/Virgin` - America\/Virgin\n\* `America\/Whitehorse` - America\/Whitehorse\n\* `America\/Winnipeg` - America\/Winnipeg\n\* `America\/Yakutat` - America\/Yakutat\n\* `America\/Yellowknife` - America\/Yellowknife\n\* `Antarctica\/Casey` - Antarctica\/Casey\n\* `Antarctica\/Davis` - Antarctica\/Davis\n\* `Antarctica\/DumontDUrville` - Antarctica\/DumontDUrville\n\* `Antarctica\/Macquarie` - Antarctica\/Macquarie\n\* `Antarctica\/Mawson` - Antarctica\/Mawson\n\* `Antarctica\/McMurdo` - Antarctica\/McMurdo\n\* `Antarctica\/Palmer` - Antarctica\/Palmer\n\* `Antarctica\/Rothera` - Antarctica\/Rothera\n\* `Antarctica\/South_Pole` - Antarctica\/South_Pole\n\* `Antarctica\/Syowa` - Antarctica\/Syowa\n\* `Antarctica\/Troll` - Antarctica\/Troll\n\* `Antarctica\/Vostok` - Antarctica\/Vostok\n\* `Arctic\/Longyearbyen` - Arctic\/Longyearbyen\n\* `Asia\/Aden` - Asia\/Aden\n\* `Asia\/Almaty` - Asia\/Almaty\n\* `Asia\/Amman` - Asia\/Amman\n\* `Asia\/Anadyr` - Asia\/Anadyr\n\* `Asia\/Aqtau` - Asia\/Aqtau\n\* `Asia\/Aqtobe` - Asia\/Aqtobe\n\* `Asia\/Ashgabat` - Asia\/Ashgabat\n\* `Asia\/Ashkhabad` - Asia\/Ashkhabad\n\* `Asia\/Atyrau` - Asia\/Atyrau\n\* `Asia\/Baghdad` - Asia\/Baghdad\n\* `Asia\/Bahrain` - Asia\/Bahrain\n\* `Asia\/Baku` - Asia\/Baku\n\* `Asia\/Bangkok` - Asia\/Bangkok\n\* `Asia\/Barnaul` - Asia\/Barnaul\n\* `Asia\/Beirut` - Asia\/Beirut\n\* `Asia\/Bishkek` - Asia\/Bishkek\n\* `Asia\/Brunei` - Asia\/Brunei\n\* `Asia\/Calcutta` - Asia\/Calcutta\n\* `Asia\/Chita` - Asia\/Chita\n\* `Asia\/Choibalsan` - Asia\/Choibalsan\n\* `Asia\/Chongqing` - Asia\/Chongqing\n\* `Asia\/Chungking` - Asia\/Chungking\n\* `Asia\/Colombo` - Asia\/Colombo\n\* `Asia\/Dacca` - Asia\/Dacca\n\* `Asia\/Damascus` - Asia\/Damascus\n\* `Asia\/Dhaka` - Asia\/Dhaka\n\* `Asia\/Dili` - Asia\/Dili\n\* `Asia\/Dubai` - Asia\/Dubai\n\* `Asia\/Dushanbe` - Asia\/Dushanbe\n\* `Asia\/Famagusta` - Asia\/Famagusta\n\* `Asia\/Gaza` - Asia\/Gaza\n\* `Asia\/Harbin` - Asia\/Harbin\n\* `Asia\/Hebron` - Asia\/Hebron\n\* `Asia\/Ho_Chi_Minh` - Asia\/Ho_Chi_Minh\n\* `Asia\/Hong_Kong` - Asia\/Hong_Kong\n\* `Asia\/Hovd` - Asia\/Hovd\n\* `Asia\/Irkutsk` - Asia\/Irkutsk\n\* `Asia\/Istanbul` - Asia\/Istanbul\n\* `Asia\/Jakarta` - Asia\/Jakarta\n\* `Asia\/Jayapura` - Asia\/Jayapura\n\* `Asia\/Jerusalem` - Asia\/Jerusalem\n\* `Asia\/Kabul` - Asia\/Kabul\n\* `Asia\/Kamchatka` - Asia\/Kamchatka\n\* `Asia\/Karachi` - Asia\/Karachi\n\* `Asia\/Kashgar` - Asia\/Kashgar\n\* `Asia\/Kathmandu` - Asia\/Kathmandu\n\* `Asia\/Katmandu` - Asia\/Katmandu\n\* `Asia\/Khandyga` - Asia\/Khandyga\n\* `Asia\/Kolkata` - Asia\/Kolkata\n\* `Asia\/Krasnoyarsk` - Asia\/Krasnoyarsk\n\* `Asia\/Kuala_Lumpur` - Asia\/Kuala_Lumpur\n\* `Asia\/Kuching` - Asia\/Kuching\n\* `Asia\/Kuwait` - Asia\/Kuwait\n\* `Asia\/Macao` - Asia\/Macao\n\* `Asia\/Macau` - Asia\/Macau\n\* `Asia\/Magadan` - Asia\/Magadan\n\* `Asia\/Makassar` - Asia\/Makassar\n\* `Asia\/Manila` - Asia\/Manila\n\* `Asia\/Muscat` - Asia\/Muscat\n\* `Asia\/Nicosia` - Asia\/Nicosia\n\* `Asia\/Novokuznetsk` - Asia\/Novokuznetsk\n\* `Asia\/Novosibirsk` - Asia\/Novosibirsk\n\* `Asia\/Omsk` - Asia\/Omsk\n\* `Asia\/Oral` - Asia\/Oral\n\* `Asia\/Phnom_Penh` - Asia\/Phnom_Penh\n\* `Asia\/Pontianak` - Asia\/Pontianak\n\* `Asia\/Pyongyang` - Asia\/Pyongyang\n\* `Asia\/Qatar` - Asia\/Qatar\n\* `Asia\/Qostanay` - Asia\/Qostanay\n\* `Asia\/Qyzylorda` - Asia\/Qyzylorda\n\* `Asia\/Rangoon` - Asia\/Rangoon\n\* `Asia\/Riyadh` - Asia\/Riyadh\n\* `Asia\/Saigon` - Asia\/Saigon\n\* `Asia\/Sakhalin` - Asia\/Sakhalin\n\* `Asia\/Samarkand` - Asia\/Samarkand\n\* `Asia\/Seoul` - Asia\/Seoul\n\* `Asia\/Shanghai` - Asia\/Shanghai\n\* `Asia\/Singapore` - Asia\/Singapore\n\* `Asia\/Srednekolymsk` - Asia\/Srednekolymsk\n\* `Asia\/Taipei` - Asia\/Taipei\n\* `Asia\/Tashkent` - Asia\/Tashkent\n\* `Asia\/Tbilisi` - Asia\/Tbilisi\n\* `Asia\/Tehran` - Asia\/Tehran\n\* `Asia\/Tel_Aviv` - Asia\/Tel_Aviv\n\* `Asia\/Thimbu` - Asia\/Thimbu\n\* `Asia\/Thimphu` - Asia\/Thimphu\n\* `Asia\/Tokyo` - Asia\/Tokyo\n\* `Asia\/Tomsk` - Asia\/Tomsk\n\* `Asia\/Ujung_Pandang` - Asia\/Ujung_Pandang\n\* `Asia\/Ulaanbaatar` - Asia\/Ulaanbaatar\n\* `Asia\/Ulan_Bator` - Asia\/Ulan_Bator\n\* `Asia\/Urumqi` - Asia\/Urumqi\n\* `Asia\/Ust-Nera` - Asia\/Ust-Nera\n\* `Asia\/Vientiane` - Asia\/Vientiane\n\* `Asia\/Vladivostok` - Asia\/Vladivostok\n\* `Asia\/Yakutsk` - Asia\/Yakutsk\n\* `Asia\/Yangon` - Asia\/Yangon\n\* `Asia\/Yekaterinburg` - Asia\/Yekaterinburg\n\* `Asia\/Yerevan` - Asia\/Yerevan\n\* `Atlantic\/Azores` - Atlantic\/Azores\n\* `Atlantic\/Bermuda` - Atlantic\/Bermuda\n\* `Atlantic\/Canary` - Atlantic\/Canary\n\* `Atlantic\/Cape_Verde` - Atlantic\/Cape_Verde\n\* `Atlantic\/Faeroe` - Atlantic\/Faeroe\n\* `Atlantic\/Faroe` - Atlantic\/Faroe\n\* `Atlantic\/Jan_Mayen` - Atlantic\/Jan_Mayen\n\* `Atlantic\/Madeira` - Atlantic\/Madeira\n\* `Atlantic\/Reykjavik` - Atlantic\/Reykjavik\n\* `Atlantic\/South_Georgia` - Atlantic\/South_Georgia\n\* `Atlantic\/St_Helena` - Atlantic\/St_Helena\n\* `Atlantic\/Stanley` - Atlantic\/Stanley\n\* `Australia\/ACT` - Australia\/ACT\n\* `Australia\/Adelaide` - Australia\/Adelaide\n\* `Australia\/Brisbane` - Australia\/Brisbane\n\* `Australia\/Broken_Hill` - Australia\/Broken_Hill\n\* `Australia\/Canberra` - Australia\/Canberra\n\* `Australia\/Currie` - Australia\/Currie\n\* `Australia\/Darwin` - Australia\/Darwin\n\* `Australia\/Eucla` - Australia\/Eucla\n\* `Australia\/Hobart` - Australia\/Hobart\n\* `Australia\/LHI` - Australia\/LHI\n\* `Australia\/Lindeman` - Australia\/Lindeman\n\* `Australia\/Lord_Howe` - Australia\/Lord_Howe\n\* `Australia\/Melbourne` - Australia\/Melbourne\n\* `Australia\/NSW` - Australia\/NSW\n\* `Australia\/North` - Australia\/North\n\* `Australia\/Perth` - Australia\/Perth\n\* `Australia\/Queensland` - Australia\/Queensland\n\* `Australia\/South` - Australia\/South\n\* `Australia\/Sydney` - Australia\/Sydney\n\* `Australia\/Tasmania` - Australia\/Tasmania\n\* `Australia\/Victoria` - Australia\/Victoria\n\* `Australia\/West` - Australia\/West\n\* `Australia\/Yancowinna` - Australia\/Yancowinna\n\* `Brazil\/Acre` - Brazil\/Acre\n\* `Brazil\/DeNoronha` - Brazil\/DeNoronha\n\* `Brazil\/East` - Brazil\/East\n\* `Brazil\/West` - Brazil\/West\n\* `CET` - CET\n\* `CST6CDT` - CST6CDT\n\* `Canada\/Atlantic` - Canada\/Atlantic\n\* `Canada\/Central` - Canada\/Central\n\* `Canada\/Eastern` - Canada\/Eastern\n\* `Canada\/Mountain` - Canada\/Mountain\n\* `Canada\/Newfoundland` - Canada\/Newfoundland\n\* `Canada\/Pacific` - Canada\/Pacific\n\* `Canada\/Saskatchewan` - Canada\/Saskatchewan\n\* `Canada\/Yukon` - Canada\/Yukon\n\* `Chile\/Continental` - Chile\/Continental\n\* `Chile\/EasterIsland` - Chile\/EasterIsland\n\* `Cuba` - Cuba\n\* `EET` - EET\n\* `EST` - EST\n\* `EST5EDT` - EST5EDT\n\* `Egypt` - Egypt\n\* `Eire` - Eire\n\* `Etc\/GMT` - Etc\/GMT\n\* `Etc\/GMT+0` - Etc\/GMT+0\n\* `Etc\/GMT+1` - Etc\/GMT+1\n\* `Etc\/GMT+10` - Etc\/GMT+10\n\* `Etc\/GMT+11` - Etc\/GMT+11\n\* `Etc\/GMT+12` - Etc\/GMT+12\n\* `Etc\/GMT+2` - Etc\/GMT+2\n\* `Etc\/GMT+3` - Etc\/GMT+3\n\* `Etc\/GMT+4` - Etc\/GMT+4\n\* `Etc\/GMT+5` - Etc\/GMT+5\n\* `Etc\/GMT+6` - Etc\/GMT+6\n\* `Etc\/GMT+7` - Etc\/GMT+7\n\* `Etc\/GMT+8` - Etc\/GMT+8\n\* `Etc\/GMT+9` - Etc\/GMT+9\n\* `Etc\/GMT-0` - Etc\/GMT-0\n\* `Etc\/GMT-1` - Etc\/GMT-1\n\* `Etc\/GMT-10` - Etc\/GMT-10\n\* `Etc\/GMT-11` - Etc\/GMT-11\n\* `Etc\/GMT-12` - Etc\/GMT-12\n\* `Etc\/GMT-13` - Etc\/GMT-13\n\* `Etc\/GMT-14` - Etc\/GMT-14\n\* `Etc\/GMT-2` - Etc\/GMT-2\n\* `Etc\/GMT-3` - Etc\/GMT-3\n\* `Etc\/GMT-4` - Etc\/GMT-4\n\* `Etc\/GMT-5` - Etc\/GMT-5\n\* `Etc\/GMT-6` - Etc\/GMT-6\n\* `Etc\/GMT-7` - Etc\/GMT-7\n\* `Etc\/GMT-8` - Etc\/GMT-8\n\* `Etc\/GMT-9` - Etc\/GMT-9\n\* `Etc\/GMT0` - Etc\/GMT0\n\* `Etc\/Greenwich` - Etc\/Greenwich\n\* `Etc\/UCT` - Etc\/UCT\n\* `Etc\/UTC` - Etc\/UTC\n\* `Etc\/Universal` - Etc\/Universal\n\* `Etc\/Zulu` - Etc\/Zulu\n\* `Europe\/Amsterdam` - Europe\/Amsterdam\n\* `Europe\/Andorra` - Europe\/Andorra\n\* `Europe\/Astrakhan` - Europe\/Astrakhan\n\* `Europe\/Athens` - Europe\/Athens\n\* `Europe\/Belfast` - Europe\/Belfast\n\* `Europe\/Belgrade` - Europe\/Belgrade\n\* `Europe\/Berlin` - Europe\/Berlin\n\* `Europe\/Bratislava` - Europe\/Bratislava\n\* `Europe\/Brussels` - Europe\/Brussels\n\* `Europe\/Bucharest` - Europe\/Bucharest\n\* `Europe\/Budapest` - Europe\/Budapest\n\* `Europe\/Busingen` - Europe\/Busingen\n\* `Europe\/Chisinau` - Europe\/Chisinau\n\* `Europe\/Copenhagen` - Europe\/Copenhagen\n\* `Europe\/Dublin` - Europe\/Dublin\n\* `Europe\/Gibraltar` - Europe\/Gibraltar\n\* `Europe\/Guernsey` - Europe\/Guernsey\n\* `Europe\/Helsinki` - Europe\/Helsinki\n\* `Europe\/Isle_of_Man` - Europe\/Isle_of_Man\n\* `Europe\/Istanbul` - Europe\/Istanbul\n\* `Europe\/Jersey` - Europe\/Jersey\n\* `Europe\/Kaliningrad` - Europe\/Kaliningrad\n\* `Europe\/Kiev` - Europe\/Kiev\n\* `Europe\/Kirov` - Europe\/Kirov\n\* `Europe\/Kyiv` - Europe\/Kyiv\n\* `Europe\/Lisbon` - Europe\/Lisbon\n\* `Europe\/Ljubljana` - Europe\/Ljubljana\n\* `Europe\/London` - Europe\/London\n\* `Europe\/Luxembourg` - Europe\/Luxembourg\n\* `Europe\/Madrid` - Europe\/Madrid\n\* `Europe\/Malta` - Europe\/Malta\n\* `Europe\/Mariehamn` - Europe\/Mariehamn\n\* `Europe\/Minsk` - Europe\/Minsk\n\* `Europe\/Monaco` - Europe\/Monaco\n\* `Europe\/Moscow` - Europe\/Moscow\n\* `Europe\/Nicosia` - Europe\/Nicosia\n\* `Europe\/Oslo` - Europe\/Oslo\n\* `Europe\/Paris` - Europe\/Paris\n\* `Europe\/Podgorica` - Europe\/Podgorica\n\* `Europe\/Prague` - Europe\/Prague\n\* `Europe\/Riga` - Europe\/Riga\n\* `Europe\/Rome` - Europe\/Rome\n\* `Europe\/Samara` - Europe\/Samara\n\* `Europe\/San_Marino` - Europe\/San_Marino\n\* `Europe\/Sarajevo` - Europe\/Sarajevo\n\* `Europe\/Saratov` - Europe\/Saratov\n\* `Europe\/Simferopol` - Europe\/Simferopol\n\* `Europe\/Skopje` - Europe\/Skopje\n\* `Europe\/Sofia` - Europe\/Sofia\n\* `Europe\/Stockholm` - Europe\/Stockholm\n\* `Europe\/Tallinn` - Europe\/Tallinn\n\* `Europe\/Tirane` - Europe\/Tirane\n\* `Europe\/Tiraspol` - Europe\/Tiraspol\n\* `Europe\/Ulyanovsk` - Europe\/Ulyanovsk\n\* `Europe\/Uzhgorod` - Europe\/Uzhgorod\n\* `Europe\/Vaduz` - Europe\/Vaduz\n\* `Europe\/Vatican` - Europe\/Vatican\n\* `Europe\/Vienna` - Europe\/Vienna\n\* `Europe\/Vilnius` - Europe\/Vilnius\n\* `Europe\/Volgograd` - Europe\/Volgograd\n\* `Europe\/Warsaw` - Europe\/Warsaw\n\* `Europe\/Zagreb` - Europe\/Zagreb\n\* `Europe\/Zaporozhye` - Europe\/Zaporozhye\n\* `Europe\/Zurich` - Europe\/Zurich\n\* `GB` - GB\n\* `GB-Eire` - GB-Eire\n\* `GMT` - GMT\n\* `GMT+0` - GMT+0\n\* `GMT-0` - GMT-0\n\* `GMT0` - GMT0\n\* `Greenwich` - Greenwich\n\* `HST` - HST\n\* `Hongkong` - Hongkong\n\* `Iceland` - Iceland\n\* `Indian\/Antananarivo` - Indian\/Antananarivo\n\* `Indian\/Chagos` - Indian\/Chagos\n\* `Indian\/Christmas` - Indian\/Christmas\n\* `Indian\/Cocos` - Indian\/Cocos\n\* `Indian\/Comoro` - Indian\/Comoro\n\* `Indian\/Kerguelen` - Indian\/Kerguelen\n\* `Indian\/Mahe` - Indian\/Mahe\n\* `Indian\/Maldives` - Indian\/Maldives\n\* `Indian\/Mauritius` - Indian\/Mauritius\n\* `Indian\/Mayotte` - Indian\/Mayotte\n\* `Indian\/Reunion` - Indian\/Reunion\n\* `Iran` - Iran\n\* `Israel` - Israel\n\* `Jamaica` - Jamaica\n\* `Japan` - Japan\n\* `Kwajalein` - Kwajalein\n\* `Libya` - Libya\n\* `MET` - MET\n\* `MST` - MST\n\* `MST7MDT` - MST7MDT\n\* `Mexico\/BajaNorte` - Mexico\/BajaNorte\n\* `Mexico\/BajaSur` - Mexico\/BajaSur\n\* `Mexico\/General` - Mexico\/General\n\* `NZ` - NZ\n\* `NZ-CHAT` - NZ-CHAT\n\* `Navajo` - Navajo\n\* `PRC` - PRC\n\* `PST8PDT` - PST8PDT\n\* `Pacific\/Apia` - Pacific\/Apia\n\* `Pacific\/Auckland` - Pacific\/Auckland\n\* `Pacific\/Bougainville` - Pacific\/Bougainville\n\* `Pacific\/Chatham` - Pacific\/Chatham\n\* `Pacific\/Chuuk` - Pacific\/Chuuk\n\* `Pacific\/Easter` - Pacific\/Easter\n\* `Pacific\/Efate` - Pacific\/Efate\n\* `Pacific\/Enderbury` - Pacific\/Enderbury\n\* `Pacific\/Fakaofo` - Pacific\/Fakaofo\n\* `Pacific\/Fiji` - Pacific\/Fiji\n\* `Pacific\/Funafuti` - Pacific\/Funafuti\n\* `Pacific\/Galapagos` - Pacific\/Galapagos\n\* `Pacific\/Gambier` - Pacific\/Gambier\n\* `Pacific\/Guadalcanal` - Pacific\/Guadalcanal\n\* `Pacific\/Guam` - Pacific\/Guam\n\* `Pacific\/Honolulu` - Pacific\/Honolulu\n\* `Pacific\/Johnston` - Pacific\/Johnston\n\* `Pacific\/Kanton` - Pacific\/Kanton\n\* `Pacific\/Kiritimati` - Pacific\/Kiritimati\n\* `Pacific\/Kosrae` - Pacific\/Kosrae\n\* `Pacific\/Kwajalein` - Pacific\/Kwajalein\n\* `Pacific\/Majuro` - Pacific\/Majuro\n\* `Pacific\/Marquesas` - Pacific\/Marquesas\n\* `Pacific\/Midway` - Pacific\/Midway\n\* `Pacific\/Nauru` - Pacific\/Nauru\n\* `Pacific\/Niue` - Pacific\/Niue\n\* `Pacific\/Norfolk` - Pacific\/Norfolk\n\* `Pacific\/Noumea` - Pacific\/Noumea\n\* `Pacific\/Pago_Pago` - Pacific\/Pago_Pago\n\* `Pacific\/Palau` - Pacific\/Palau\n\* `Pacific\/Pitcairn` - Pacific\/Pitcairn\n\* `Pacific\/Pohnpei` - Pacific\/Pohnpei\n\* `Pacific\/Ponape` - Pacific\/Ponape\n\* `Pacific\/Port_Moresby` - Pacific\/Port_Moresby\n\* `Pacific\/Rarotonga` - Pacific\/Rarotonga\n\* `Pacific\/Saipan` - Pacific\/Saipan\n\* `Pacific\/Samoa` - Pacific\/Samoa\n\* `Pacific\/Tahiti` - Pacific\/Tahiti\n\* `Pacific\/Tarawa` - Pacific\/Tarawa\n\* `Pacific\/Tongatapu` - Pacific\/Tongatapu\n\* `Pacific\/Truk` - Pacific\/Truk\n\* `Pacific\/Wake` - Pacific\/Wake\n\* `Pacific\/Wallis` - Pacific\/Wallis\n\* `Pacific\/Yap` - Pacific\/Yap\n\* `Poland` - Poland\n\* `Portugal` - Portugal\n\* `ROC` - ROC\n\* `ROK` - ROK\n\* `Singapore` - Singapore\n\* `Turkey` - Turkey\n\* `UCT` - UCT\n\* `US\/Alaska` - US\/Alaska\n\* `US\/Aleutian` - US\/Aleutian\n\* `US\/Arizona` - US\/Arizona\n\* `US\/Central` - US\/Central\n\* `US\/East-Indiana` - US\/East-Indiana\n\* `US\/Eastern` - US\/Eastern\n\* `US\/Hawaii` - US\/Hawaii\n\* `US\/Indiana-Starke` - US\/Indiana-Starke\n\* `US\/Michigan` - US\/Michigan\n\* `US\/Mountain` - US\/Mountain\n\* `US\/Pacific` - US\/Pacific\n\* `US\/Samoa` - US\/Samoa\n\* `UTC` - UTC\n\* `Universal` - Universal\n\* `W-SU` - W-SU\n\* `WET` - WET\n\* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(organizationsProjectsLogsConfigPartialUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat('decimal', organizationsProjectsLogsConfigPartialUpdateBodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(organizationsProjectsLogsConfigPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(organizationsProjectsLogsConfigPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(organizationsProjectsLogsConfigPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('\* `0` - Sunday\n\* `1` - Monday'),
                zod.null(),
            ])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n\* `0` - Sunday\n\* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(organizationsProjectsLogsConfigPartialUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations \/ live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(
                        organizationsProjectsLogsConfigPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax
                    )
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsLogsConfigPartialUpdateBodyDefaultDataThemeMin)
            .max(organizationsProjectsLogsConfigPartialUpdateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Projects for the current organization.
 */
export const organizationsProjectsResetTokenPartialUpdateBodyNameMax = 200

export const organizationsProjectsResetTokenPartialUpdateBodyProductDescriptionMax = 1000

export const organizationsProjectsResetTokenPartialUpdateBodyAppUrlsItemMax = 200

export const organizationsProjectsResetTokenPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsResetTokenPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const organizationsProjectsResetTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsResetTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsResetTokenPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsResetTokenPartialUpdateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsResetTokenPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsResetTokenPartialUpdateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsResetTokenPartialUpdateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsResetTokenPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsResetTokenPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsResetTokenPartialUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(zod.string().max(organizationsProjectsResetTokenPartialUpdateBodyAppUrlsItemMax).nullable())
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal\/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal\/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America\/Los_Angeles`).\n\n\* `Africa\/Abidjan` - Africa\/Abidjan\n\* `Africa\/Accra` - Africa\/Accra\n\* `Africa\/Addis_Ababa` - Africa\/Addis_Ababa\n\* `Africa\/Algiers` - Africa\/Algiers\n\* `Africa\/Asmara` - Africa\/Asmara\n\* `Africa\/Asmera` - Africa\/Asmera\n\* `Africa\/Bamako` - Africa\/Bamako\n\* `Africa\/Bangui` - Africa\/Bangui\n\* `Africa\/Banjul` - Africa\/Banjul\n\* `Africa\/Bissau` - Africa\/Bissau\n\* `Africa\/Blantyre` - Africa\/Blantyre\n\* `Africa\/Brazzaville` - Africa\/Brazzaville\n\* `Africa\/Bujumbura` - Africa\/Bujumbura\n\* `Africa\/Cairo` - Africa\/Cairo\n\* `Africa\/Casablanca` - Africa\/Casablanca\n\* `Africa\/Ceuta` - Africa\/Ceuta\n\* `Africa\/Conakry` - Africa\/Conakry\n\* `Africa\/Dakar` - Africa\/Dakar\n\* `Africa\/Dar_es_Salaam` - Africa\/Dar_es_Salaam\n\* `Africa\/Djibouti` - Africa\/Djibouti\n\* `Africa\/Douala` - Africa\/Douala\n\* `Africa\/El_Aaiun` - Africa\/El_Aaiun\n\* `Africa\/Freetown` - Africa\/Freetown\n\* `Africa\/Gaborone` - Africa\/Gaborone\n\* `Africa\/Harare` - Africa\/Harare\n\* `Africa\/Johannesburg` - Africa\/Johannesburg\n\* `Africa\/Juba` - Africa\/Juba\n\* `Africa\/Kampala` - Africa\/Kampala\n\* `Africa\/Khartoum` - Africa\/Khartoum\n\* `Africa\/Kigali` - Africa\/Kigali\n\* `Africa\/Kinshasa` - Africa\/Kinshasa\n\* `Africa\/Lagos` - Africa\/Lagos\n\* `Africa\/Libreville` - Africa\/Libreville\n\* `Africa\/Lome` - Africa\/Lome\n\* `Africa\/Luanda` - Africa\/Luanda\n\* `Africa\/Lubumbashi` - Africa\/Lubumbashi\n\* `Africa\/Lusaka` - Africa\/Lusaka\n\* `Africa\/Malabo` - Africa\/Malabo\n\* `Africa\/Maputo` - Africa\/Maputo\n\* `Africa\/Maseru` - Africa\/Maseru\n\* `Africa\/Mbabane` - Africa\/Mbabane\n\* `Africa\/Mogadishu` - Africa\/Mogadishu\n\* `Africa\/Monrovia` - Africa\/Monrovia\n\* `Africa\/Nairobi` - Africa\/Nairobi\n\* `Africa\/Ndjamena` - Africa\/Ndjamena\n\* `Africa\/Niamey` - Africa\/Niamey\n\* `Africa\/Nouakchott` - Africa\/Nouakchott\n\* `Africa\/Ouagadougou` - Africa\/Ouagadougou\n\* `Africa\/Porto-Novo` - Africa\/Porto-Novo\n\* `Africa\/Sao_Tome` - Africa\/Sao_Tome\n\* `Africa\/Timbuktu` - Africa\/Timbuktu\n\* `Africa\/Tripoli` - Africa\/Tripoli\n\* `Africa\/Tunis` - Africa\/Tunis\n\* `Africa\/Windhoek` - Africa\/Windhoek\n\* `America\/Adak` - America\/Adak\n\* `America\/Anchorage` - America\/Anchorage\n\* `America\/Anguilla` - America\/Anguilla\n\* `America\/Antigua` - America\/Antigua\n\* `America\/Araguaina` - America\/Araguaina\n\* `America\/Argentina\/Buenos_Aires` - America\/Argentina\/Buenos_Aires\n\* `America\/Argentina\/Catamarca` - America\/Argentina\/Catamarca\n\* `America\/Argentina\/ComodRivadavia` - America\/Argentina\/ComodRivadavia\n\* `America\/Argentina\/Cordoba` - America\/Argentina\/Cordoba\n\* `America\/Argentina\/Jujuy` - America\/Argentina\/Jujuy\n\* `America\/Argentina\/La_Rioja` - America\/Argentina\/La_Rioja\n\* `America\/Argentina\/Mendoza` - America\/Argentina\/Mendoza\n\* `America\/Argentina\/Rio_Gallegos` - America\/Argentina\/Rio_Gallegos\n\* `America\/Argentina\/Salta` - America\/Argentina\/Salta\n\* `America\/Argentina\/San_Juan` - America\/Argentina\/San_Juan\n\* `America\/Argentina\/San_Luis` - America\/Argentina\/San_Luis\n\* `America\/Argentina\/Tucuman` - America\/Argentina\/Tucuman\n\* `America\/Argentina\/Ushuaia` - America\/Argentina\/Ushuaia\n\* `America\/Aruba` - America\/Aruba\n\* `America\/Asuncion` - America\/Asuncion\n\* `America\/Atikokan` - America\/Atikokan\n\* `America\/Atka` - America\/Atka\n\* `America\/Bahia` - America\/Bahia\n\* `America\/Bahia_Banderas` - America\/Bahia_Banderas\n\* `America\/Barbados` - America\/Barbados\n\* `America\/Belem` - America\/Belem\n\* `America\/Belize` - America\/Belize\n\* `America\/Blanc-Sablon` - America\/Blanc-Sablon\n\* `America\/Boa_Vista` - America\/Boa_Vista\n\* `America\/Bogota` - America\/Bogota\n\* `America\/Boise` - America\/Boise\n\* `America\/Buenos_Aires` - America\/Buenos_Aires\n\* `America\/Cambridge_Bay` - America\/Cambridge_Bay\n\* `America\/Campo_Grande` - America\/Campo_Grande\n\* `America\/Cancun` - America\/Cancun\n\* `America\/Caracas` - America\/Caracas\n\* `America\/Catamarca` - America\/Catamarca\n\* `America\/Cayenne` - America\/Cayenne\n\* `America\/Cayman` - America\/Cayman\n\* `America\/Chicago` - America\/Chicago\n\* `America\/Chihuahua` - America\/Chihuahua\n\* `America\/Ciudad_Juarez` - America\/Ciudad_Juarez\n\* `America\/Coral_Harbour` - America\/Coral_Harbour\n\* `America\/Cordoba` - America\/Cordoba\n\* `America\/Costa_Rica` - America\/Costa_Rica\n\* `America\/Creston` - America\/Creston\n\* `America\/Cuiaba` - America\/Cuiaba\n\* `America\/Curacao` - America\/Curacao\n\* `America\/Danmarkshavn` - America\/Danmarkshavn\n\* `America\/Dawson` - America\/Dawson\n\* `America\/Dawson_Creek` - America\/Dawson_Creek\n\* `America\/Denver` - America\/Denver\n\* `America\/Detroit` - America\/Detroit\n\* `America\/Dominica` - America\/Dominica\n\* `America\/Edmonton` - America\/Edmonton\n\* `America\/Eirunepe` - America\/Eirunepe\n\* `America\/El_Salvador` - America\/El_Salvador\n\* `America\/Ensenada` - America\/Ensenada\n\* `America\/Fort_Nelson` - America\/Fort_Nelson\n\* `America\/Fort_Wayne` - America\/Fort_Wayne\n\* `America\/Fortaleza` - America\/Fortaleza\n\* `America\/Glace_Bay` - America\/Glace_Bay\n\* `America\/Godthab` - America\/Godthab\n\* `America\/Goose_Bay` - America\/Goose_Bay\n\* `America\/Grand_Turk` - America\/Grand_Turk\n\* `America\/Grenada` - America\/Grenada\n\* `America\/Guadeloupe` - America\/Guadeloupe\n\* `America\/Guatemala` - America\/Guatemala\n\* `America\/Guayaquil` - America\/Guayaquil\n\* `America\/Guyana` - America\/Guyana\n\* `America\/Halifax` - America\/Halifax\n\* `America\/Havana` - America\/Havana\n\* `America\/Hermosillo` - America\/Hermosillo\n\* `America\/Indiana\/Indianapolis` - America\/Indiana\/Indianapolis\n\* `America\/Indiana\/Knox` - America\/Indiana\/Knox\n\* `America\/Indiana\/Marengo` - America\/Indiana\/Marengo\n\* `America\/Indiana\/Petersburg` - America\/Indiana\/Petersburg\n\* `America\/Indiana\/Tell_City` - America\/Indiana\/Tell_City\n\* `America\/Indiana\/Vevay` - America\/Indiana\/Vevay\n\* `America\/Indiana\/Vincennes` - America\/Indiana\/Vincennes\n\* `America\/Indiana\/Winamac` - America\/Indiana\/Winamac\n\* `America\/Indianapolis` - America\/Indianapolis\n\* `America\/Inuvik` - America\/Inuvik\n\* `America\/Iqaluit` - America\/Iqaluit\n\* `America\/Jamaica` - America\/Jamaica\n\* `America\/Jujuy` - America\/Jujuy\n\* `America\/Juneau` - America\/Juneau\n\* `America\/Kentucky\/Louisville` - America\/Kentucky\/Louisville\n\* `America\/Kentucky\/Monticello` - America\/Kentucky\/Monticello\n\* `America\/Knox_IN` - America\/Knox_IN\n\* `America\/Kralendijk` - America\/Kralendijk\n\* `America\/La_Paz` - America\/La_Paz\n\* `America\/Lima` - America\/Lima\n\* `America\/Los_Angeles` - America\/Los_Angeles\n\* `America\/Louisville` - America\/Louisville\n\* `America\/Lower_Princes` - America\/Lower_Princes\n\* `America\/Maceio` - America\/Maceio\n\* `America\/Managua` - America\/Managua\n\* `America\/Manaus` - America\/Manaus\n\* `America\/Marigot` - America\/Marigot\n\* `America\/Martinique` - America\/Martinique\n\* `America\/Matamoros` - America\/Matamoros\n\* `America\/Mazatlan` - America\/Mazatlan\n\* `America\/Mendoza` - America\/Mendoza\n\* `America\/Menominee` - America\/Menominee\n\* `America\/Merida` - America\/Merida\n\* `America\/Metlakatla` - America\/Metlakatla\n\* `America\/Mexico_City` - America\/Mexico_City\n\* `America\/Miquelon` - America\/Miquelon\n\* `America\/Moncton` - America\/Moncton\n\* `America\/Monterrey` - America\/Monterrey\n\* `America\/Montevideo` - America\/Montevideo\n\* `America\/Montreal` - America\/Montreal\n\* `America\/Montserrat` - America\/Montserrat\n\* `America\/Nassau` - America\/Nassau\n\* `America\/New_York` - America\/New_York\n\* `America\/Nipigon` - America\/Nipigon\n\* `America\/Nome` - America\/Nome\n\* `America\/Noronha` - America\/Noronha\n\* `America\/North_Dakota\/Beulah` - America\/North_Dakota\/Beulah\n\* `America\/North_Dakota\/Center` - America\/North_Dakota\/Center\n\* `America\/North_Dakota\/New_Salem` - America\/North_Dakota\/New_Salem\n\* `America\/Nuuk` - America\/Nuuk\n\* `America\/Ojinaga` - America\/Ojinaga\n\* `America\/Panama` - America\/Panama\n\* `America\/Pangnirtung` - America\/Pangnirtung\n\* `America\/Paramaribo` - America\/Paramaribo\n\* `America\/Phoenix` - America\/Phoenix\n\* `America\/Port-au-Prince` - America\/Port-au-Prince\n\* `America\/Port_of_Spain` - America\/Port_of_Spain\n\* `America\/Porto_Acre` - America\/Porto_Acre\n\* `America\/Porto_Velho` - America\/Porto_Velho\n\* `America\/Puerto_Rico` - America\/Puerto_Rico\n\* `America\/Punta_Arenas` - America\/Punta_Arenas\n\* `America\/Rainy_River` - America\/Rainy_River\n\* `America\/Rankin_Inlet` - America\/Rankin_Inlet\n\* `America\/Recife` - America\/Recife\n\* `America\/Regina` - America\/Regina\n\* `America\/Resolute` - America\/Resolute\n\* `America\/Rio_Branco` - America\/Rio_Branco\n\* `America\/Rosario` - America\/Rosario\n\* `America\/Santa_Isabel` - America\/Santa_Isabel\n\* `America\/Santarem` - America\/Santarem\n\* `America\/Santiago` - America\/Santiago\n\* `America\/Santo_Domingo` - America\/Santo_Domingo\n\* `America\/Sao_Paulo` - America\/Sao_Paulo\n\* `America\/Scoresbysund` - America\/Scoresbysund\n\* `America\/Shiprock` - America\/Shiprock\n\* `America\/Sitka` - America\/Sitka\n\* `America\/St_Barthelemy` - America\/St_Barthelemy\n\* `America\/St_Johns` - America\/St_Johns\n\* `America\/St_Kitts` - America\/St_Kitts\n\* `America\/St_Lucia` - America\/St_Lucia\n\* `America\/St_Thomas` - America\/St_Thomas\n\* `America\/St_Vincent` - America\/St_Vincent\n\* `America\/Swift_Current` - America\/Swift_Current\n\* `America\/Tegucigalpa` - America\/Tegucigalpa\n\* `America\/Thule` - America\/Thule\n\* `America\/Thunder_Bay` - America\/Thunder_Bay\n\* `America\/Tijuana` - America\/Tijuana\n\* `America\/Toronto` - America\/Toronto\n\* `America\/Tortola` - America\/Tortola\n\* `America\/Vancouver` - America\/Vancouver\n\* `America\/Virgin` - America\/Virgin\n\* `America\/Whitehorse` - America\/Whitehorse\n\* `America\/Winnipeg` - America\/Winnipeg\n\* `America\/Yakutat` - America\/Yakutat\n\* `America\/Yellowknife` - America\/Yellowknife\n\* `Antarctica\/Casey` - Antarctica\/Casey\n\* `Antarctica\/Davis` - Antarctica\/Davis\n\* `Antarctica\/DumontDUrville` - Antarctica\/DumontDUrville\n\* `Antarctica\/Macquarie` - Antarctica\/Macquarie\n\* `Antarctica\/Mawson` - Antarctica\/Mawson\n\* `Antarctica\/McMurdo` - Antarctica\/McMurdo\n\* `Antarctica\/Palmer` - Antarctica\/Palmer\n\* `Antarctica\/Rothera` - Antarctica\/Rothera\n\* `Antarctica\/South_Pole` - Antarctica\/South_Pole\n\* `Antarctica\/Syowa` - Antarctica\/Syowa\n\* `Antarctica\/Troll` - Antarctica\/Troll\n\* `Antarctica\/Vostok` - Antarctica\/Vostok\n\* `Arctic\/Longyearbyen` - Arctic\/Longyearbyen\n\* `Asia\/Aden` - Asia\/Aden\n\* `Asia\/Almaty` - Asia\/Almaty\n\* `Asia\/Amman` - Asia\/Amman\n\* `Asia\/Anadyr` - Asia\/Anadyr\n\* `Asia\/Aqtau` - Asia\/Aqtau\n\* `Asia\/Aqtobe` - Asia\/Aqtobe\n\* `Asia\/Ashgabat` - Asia\/Ashgabat\n\* `Asia\/Ashkhabad` - Asia\/Ashkhabad\n\* `Asia\/Atyrau` - Asia\/Atyrau\n\* `Asia\/Baghdad` - Asia\/Baghdad\n\* `Asia\/Bahrain` - Asia\/Bahrain\n\* `Asia\/Baku` - Asia\/Baku\n\* `Asia\/Bangkok` - Asia\/Bangkok\n\* `Asia\/Barnaul` - Asia\/Barnaul\n\* `Asia\/Beirut` - Asia\/Beirut\n\* `Asia\/Bishkek` - Asia\/Bishkek\n\* `Asia\/Brunei` - Asia\/Brunei\n\* `Asia\/Calcutta` - Asia\/Calcutta\n\* `Asia\/Chita` - Asia\/Chita\n\* `Asia\/Choibalsan` - Asia\/Choibalsan\n\* `Asia\/Chongqing` - Asia\/Chongqing\n\* `Asia\/Chungking` - Asia\/Chungking\n\* `Asia\/Colombo` - Asia\/Colombo\n\* `Asia\/Dacca` - Asia\/Dacca\n\* `Asia\/Damascus` - Asia\/Damascus\n\* `Asia\/Dhaka` - Asia\/Dhaka\n\* `Asia\/Dili` - Asia\/Dili\n\* `Asia\/Dubai` - Asia\/Dubai\n\* `Asia\/Dushanbe` - Asia\/Dushanbe\n\* `Asia\/Famagusta` - Asia\/Famagusta\n\* `Asia\/Gaza` - Asia\/Gaza\n\* `Asia\/Harbin` - Asia\/Harbin\n\* `Asia\/Hebron` - Asia\/Hebron\n\* `Asia\/Ho_Chi_Minh` - Asia\/Ho_Chi_Minh\n\* `Asia\/Hong_Kong` - Asia\/Hong_Kong\n\* `Asia\/Hovd` - Asia\/Hovd\n\* `Asia\/Irkutsk` - Asia\/Irkutsk\n\* `Asia\/Istanbul` - Asia\/Istanbul\n\* `Asia\/Jakarta` - Asia\/Jakarta\n\* `Asia\/Jayapura` - Asia\/Jayapura\n\* `Asia\/Jerusalem` - Asia\/Jerusalem\n\* `Asia\/Kabul` - Asia\/Kabul\n\* `Asia\/Kamchatka` - Asia\/Kamchatka\n\* `Asia\/Karachi` - Asia\/Karachi\n\* `Asia\/Kashgar` - Asia\/Kashgar\n\* `Asia\/Kathmandu` - Asia\/Kathmandu\n\* `Asia\/Katmandu` - Asia\/Katmandu\n\* `Asia\/Khandyga` - Asia\/Khandyga\n\* `Asia\/Kolkata` - Asia\/Kolkata\n\* `Asia\/Krasnoyarsk` - Asia\/Krasnoyarsk\n\* `Asia\/Kuala_Lumpur` - Asia\/Kuala_Lumpur\n\* `Asia\/Kuching` - Asia\/Kuching\n\* `Asia\/Kuwait` - Asia\/Kuwait\n\* `Asia\/Macao` - Asia\/Macao\n\* `Asia\/Macau` - Asia\/Macau\n\* `Asia\/Magadan` - Asia\/Magadan\n\* `Asia\/Makassar` - Asia\/Makassar\n\* `Asia\/Manila` - Asia\/Manila\n\* `Asia\/Muscat` - Asia\/Muscat\n\* `Asia\/Nicosia` - Asia\/Nicosia\n\* `Asia\/Novokuznetsk` - Asia\/Novokuznetsk\n\* `Asia\/Novosibirsk` - Asia\/Novosibirsk\n\* `Asia\/Omsk` - Asia\/Omsk\n\* `Asia\/Oral` - Asia\/Oral\n\* `Asia\/Phnom_Penh` - Asia\/Phnom_Penh\n\* `Asia\/Pontianak` - Asia\/Pontianak\n\* `Asia\/Pyongyang` - Asia\/Pyongyang\n\* `Asia\/Qatar` - Asia\/Qatar\n\* `Asia\/Qostanay` - Asia\/Qostanay\n\* `Asia\/Qyzylorda` - Asia\/Qyzylorda\n\* `Asia\/Rangoon` - Asia\/Rangoon\n\* `Asia\/Riyadh` - Asia\/Riyadh\n\* `Asia\/Saigon` - Asia\/Saigon\n\* `Asia\/Sakhalin` - Asia\/Sakhalin\n\* `Asia\/Samarkand` - Asia\/Samarkand\n\* `Asia\/Seoul` - Asia\/Seoul\n\* `Asia\/Shanghai` - Asia\/Shanghai\n\* `Asia\/Singapore` - Asia\/Singapore\n\* `Asia\/Srednekolymsk` - Asia\/Srednekolymsk\n\* `Asia\/Taipei` - Asia\/Taipei\n\* `Asia\/Tashkent` - Asia\/Tashkent\n\* `Asia\/Tbilisi` - Asia\/Tbilisi\n\* `Asia\/Tehran` - Asia\/Tehran\n\* `Asia\/Tel_Aviv` - Asia\/Tel_Aviv\n\* `Asia\/Thimbu` - Asia\/Thimbu\n\* `Asia\/Thimphu` - Asia\/Thimphu\n\* `Asia\/Tokyo` - Asia\/Tokyo\n\* `Asia\/Tomsk` - Asia\/Tomsk\n\* `Asia\/Ujung_Pandang` - Asia\/Ujung_Pandang\n\* `Asia\/Ulaanbaatar` - Asia\/Ulaanbaatar\n\* `Asia\/Ulan_Bator` - Asia\/Ulan_Bator\n\* `Asia\/Urumqi` - Asia\/Urumqi\n\* `Asia\/Ust-Nera` - Asia\/Ust-Nera\n\* `Asia\/Vientiane` - Asia\/Vientiane\n\* `Asia\/Vladivostok` - Asia\/Vladivostok\n\* `Asia\/Yakutsk` - Asia\/Yakutsk\n\* `Asia\/Yangon` - Asia\/Yangon\n\* `Asia\/Yekaterinburg` - Asia\/Yekaterinburg\n\* `Asia\/Yerevan` - Asia\/Yerevan\n\* `Atlantic\/Azores` - Atlantic\/Azores\n\* `Atlantic\/Bermuda` - Atlantic\/Bermuda\n\* `Atlantic\/Canary` - Atlantic\/Canary\n\* `Atlantic\/Cape_Verde` - Atlantic\/Cape_Verde\n\* `Atlantic\/Faeroe` - Atlantic\/Faeroe\n\* `Atlantic\/Faroe` - Atlantic\/Faroe\n\* `Atlantic\/Jan_Mayen` - Atlantic\/Jan_Mayen\n\* `Atlantic\/Madeira` - Atlantic\/Madeira\n\* `Atlantic\/Reykjavik` - Atlantic\/Reykjavik\n\* `Atlantic\/South_Georgia` - Atlantic\/South_Georgia\n\* `Atlantic\/St_Helena` - Atlantic\/St_Helena\n\* `Atlantic\/Stanley` - Atlantic\/Stanley\n\* `Australia\/ACT` - Australia\/ACT\n\* `Australia\/Adelaide` - Australia\/Adelaide\n\* `Australia\/Brisbane` - Australia\/Brisbane\n\* `Australia\/Broken_Hill` - Australia\/Broken_Hill\n\* `Australia\/Canberra` - Australia\/Canberra\n\* `Australia\/Currie` - Australia\/Currie\n\* `Australia\/Darwin` - Australia\/Darwin\n\* `Australia\/Eucla` - Australia\/Eucla\n\* `Australia\/Hobart` - Australia\/Hobart\n\* `Australia\/LHI` - Australia\/LHI\n\* `Australia\/Lindeman` - Australia\/Lindeman\n\* `Australia\/Lord_Howe` - Australia\/Lord_Howe\n\* `Australia\/Melbourne` - Australia\/Melbourne\n\* `Australia\/NSW` - Australia\/NSW\n\* `Australia\/North` - Australia\/North\n\* `Australia\/Perth` - Australia\/Perth\n\* `Australia\/Queensland` - Australia\/Queensland\n\* `Australia\/South` - Australia\/South\n\* `Australia\/Sydney` - Australia\/Sydney\n\* `Australia\/Tasmania` - Australia\/Tasmania\n\* `Australia\/Victoria` - Australia\/Victoria\n\* `Australia\/West` - Australia\/West\n\* `Australia\/Yancowinna` - Australia\/Yancowinna\n\* `Brazil\/Acre` - Brazil\/Acre\n\* `Brazil\/DeNoronha` - Brazil\/DeNoronha\n\* `Brazil\/East` - Brazil\/East\n\* `Brazil\/West` - Brazil\/West\n\* `CET` - CET\n\* `CST6CDT` - CST6CDT\n\* `Canada\/Atlantic` - Canada\/Atlantic\n\* `Canada\/Central` - Canada\/Central\n\* `Canada\/Eastern` - Canada\/Eastern\n\* `Canada\/Mountain` - Canada\/Mountain\n\* `Canada\/Newfoundland` - Canada\/Newfoundland\n\* `Canada\/Pacific` - Canada\/Pacific\n\* `Canada\/Saskatchewan` - Canada\/Saskatchewan\n\* `Canada\/Yukon` - Canada\/Yukon\n\* `Chile\/Continental` - Chile\/Continental\n\* `Chile\/EasterIsland` - Chile\/EasterIsland\n\* `Cuba` - Cuba\n\* `EET` - EET\n\* `EST` - EST\n\* `EST5EDT` - EST5EDT\n\* `Egypt` - Egypt\n\* `Eire` - Eire\n\* `Etc\/GMT` - Etc\/GMT\n\* `Etc\/GMT+0` - Etc\/GMT+0\n\* `Etc\/GMT+1` - Etc\/GMT+1\n\* `Etc\/GMT+10` - Etc\/GMT+10\n\* `Etc\/GMT+11` - Etc\/GMT+11\n\* `Etc\/GMT+12` - Etc\/GMT+12\n\* `Etc\/GMT+2` - Etc\/GMT+2\n\* `Etc\/GMT+3` - Etc\/GMT+3\n\* `Etc\/GMT+4` - Etc\/GMT+4\n\* `Etc\/GMT+5` - Etc\/GMT+5\n\* `Etc\/GMT+6` - Etc\/GMT+6\n\* `Etc\/GMT+7` - Etc\/GMT+7\n\* `Etc\/GMT+8` - Etc\/GMT+8\n\* `Etc\/GMT+9` - Etc\/GMT+9\n\* `Etc\/GMT-0` - Etc\/GMT-0\n\* `Etc\/GMT-1` - Etc\/GMT-1\n\* `Etc\/GMT-10` - Etc\/GMT-10\n\* `Etc\/GMT-11` - Etc\/GMT-11\n\* `Etc\/GMT-12` - Etc\/GMT-12\n\* `Etc\/GMT-13` - Etc\/GMT-13\n\* `Etc\/GMT-14` - Etc\/GMT-14\n\* `Etc\/GMT-2` - Etc\/GMT-2\n\* `Etc\/GMT-3` - Etc\/GMT-3\n\* `Etc\/GMT-4` - Etc\/GMT-4\n\* `Etc\/GMT-5` - Etc\/GMT-5\n\* `Etc\/GMT-6` - Etc\/GMT-6\n\* `Etc\/GMT-7` - Etc\/GMT-7\n\* `Etc\/GMT-8` - Etc\/GMT-8\n\* `Etc\/GMT-9` - Etc\/GMT-9\n\* `Etc\/GMT0` - Etc\/GMT0\n\* `Etc\/Greenwich` - Etc\/Greenwich\n\* `Etc\/UCT` - Etc\/UCT\n\* `Etc\/UTC` - Etc\/UTC\n\* `Etc\/Universal` - Etc\/Universal\n\* `Etc\/Zulu` - Etc\/Zulu\n\* `Europe\/Amsterdam` - Europe\/Amsterdam\n\* `Europe\/Andorra` - Europe\/Andorra\n\* `Europe\/Astrakhan` - Europe\/Astrakhan\n\* `Europe\/Athens` - Europe\/Athens\n\* `Europe\/Belfast` - Europe\/Belfast\n\* `Europe\/Belgrade` - Europe\/Belgrade\n\* `Europe\/Berlin` - Europe\/Berlin\n\* `Europe\/Bratislava` - Europe\/Bratislava\n\* `Europe\/Brussels` - Europe\/Brussels\n\* `Europe\/Bucharest` - Europe\/Bucharest\n\* `Europe\/Budapest` - Europe\/Budapest\n\* `Europe\/Busingen` - Europe\/Busingen\n\* `Europe\/Chisinau` - Europe\/Chisinau\n\* `Europe\/Copenhagen` - Europe\/Copenhagen\n\* `Europe\/Dublin` - Europe\/Dublin\n\* `Europe\/Gibraltar` - Europe\/Gibraltar\n\* `Europe\/Guernsey` - Europe\/Guernsey\n\* `Europe\/Helsinki` - Europe\/Helsinki\n\* `Europe\/Isle_of_Man` - Europe\/Isle_of_Man\n\* `Europe\/Istanbul` - Europe\/Istanbul\n\* `Europe\/Jersey` - Europe\/Jersey\n\* `Europe\/Kaliningrad` - Europe\/Kaliningrad\n\* `Europe\/Kiev` - Europe\/Kiev\n\* `Europe\/Kirov` - Europe\/Kirov\n\* `Europe\/Kyiv` - Europe\/Kyiv\n\* `Europe\/Lisbon` - Europe\/Lisbon\n\* `Europe\/Ljubljana` - Europe\/Ljubljana\n\* `Europe\/London` - Europe\/London\n\* `Europe\/Luxembourg` - Europe\/Luxembourg\n\* `Europe\/Madrid` - Europe\/Madrid\n\* `Europe\/Malta` - Europe\/Malta\n\* `Europe\/Mariehamn` - Europe\/Mariehamn\n\* `Europe\/Minsk` - Europe\/Minsk\n\* `Europe\/Monaco` - Europe\/Monaco\n\* `Europe\/Moscow` - Europe\/Moscow\n\* `Europe\/Nicosia` - Europe\/Nicosia\n\* `Europe\/Oslo` - Europe\/Oslo\n\* `Europe\/Paris` - Europe\/Paris\n\* `Europe\/Podgorica` - Europe\/Podgorica\n\* `Europe\/Prague` - Europe\/Prague\n\* `Europe\/Riga` - Europe\/Riga\n\* `Europe\/Rome` - Europe\/Rome\n\* `Europe\/Samara` - Europe\/Samara\n\* `Europe\/San_Marino` - Europe\/San_Marino\n\* `Europe\/Sarajevo` - Europe\/Sarajevo\n\* `Europe\/Saratov` - Europe\/Saratov\n\* `Europe\/Simferopol` - Europe\/Simferopol\n\* `Europe\/Skopje` - Europe\/Skopje\n\* `Europe\/Sofia` - Europe\/Sofia\n\* `Europe\/Stockholm` - Europe\/Stockholm\n\* `Europe\/Tallinn` - Europe\/Tallinn\n\* `Europe\/Tirane` - Europe\/Tirane\n\* `Europe\/Tiraspol` - Europe\/Tiraspol\n\* `Europe\/Ulyanovsk` - Europe\/Ulyanovsk\n\* `Europe\/Uzhgorod` - Europe\/Uzhgorod\n\* `Europe\/Vaduz` - Europe\/Vaduz\n\* `Europe\/Vatican` - Europe\/Vatican\n\* `Europe\/Vienna` - Europe\/Vienna\n\* `Europe\/Vilnius` - Europe\/Vilnius\n\* `Europe\/Volgograd` - Europe\/Volgograd\n\* `Europe\/Warsaw` - Europe\/Warsaw\n\* `Europe\/Zagreb` - Europe\/Zagreb\n\* `Europe\/Zaporozhye` - Europe\/Zaporozhye\n\* `Europe\/Zurich` - Europe\/Zurich\n\* `GB` - GB\n\* `GB-Eire` - GB-Eire\n\* `GMT` - GMT\n\* `GMT+0` - GMT+0\n\* `GMT-0` - GMT-0\n\* `GMT0` - GMT0\n\* `Greenwich` - Greenwich\n\* `HST` - HST\n\* `Hongkong` - Hongkong\n\* `Iceland` - Iceland\n\* `Indian\/Antananarivo` - Indian\/Antananarivo\n\* `Indian\/Chagos` - Indian\/Chagos\n\* `Indian\/Christmas` - Indian\/Christmas\n\* `Indian\/Cocos` - Indian\/Cocos\n\* `Indian\/Comoro` - Indian\/Comoro\n\* `Indian\/Kerguelen` - Indian\/Kerguelen\n\* `Indian\/Mahe` - Indian\/Mahe\n\* `Indian\/Maldives` - Indian\/Maldives\n\* `Indian\/Mauritius` - Indian\/Mauritius\n\* `Indian\/Mayotte` - Indian\/Mayotte\n\* `Indian\/Reunion` - Indian\/Reunion\n\* `Iran` - Iran\n\* `Israel` - Israel\n\* `Jamaica` - Jamaica\n\* `Japan` - Japan\n\* `Kwajalein` - Kwajalein\n\* `Libya` - Libya\n\* `MET` - MET\n\* `MST` - MST\n\* `MST7MDT` - MST7MDT\n\* `Mexico\/BajaNorte` - Mexico\/BajaNorte\n\* `Mexico\/BajaSur` - Mexico\/BajaSur\n\* `Mexico\/General` - Mexico\/General\n\* `NZ` - NZ\n\* `NZ-CHAT` - NZ-CHAT\n\* `Navajo` - Navajo\n\* `PRC` - PRC\n\* `PST8PDT` - PST8PDT\n\* `Pacific\/Apia` - Pacific\/Apia\n\* `Pacific\/Auckland` - Pacific\/Auckland\n\* `Pacific\/Bougainville` - Pacific\/Bougainville\n\* `Pacific\/Chatham` - Pacific\/Chatham\n\* `Pacific\/Chuuk` - Pacific\/Chuuk\n\* `Pacific\/Easter` - Pacific\/Easter\n\* `Pacific\/Efate` - Pacific\/Efate\n\* `Pacific\/Enderbury` - Pacific\/Enderbury\n\* `Pacific\/Fakaofo` - Pacific\/Fakaofo\n\* `Pacific\/Fiji` - Pacific\/Fiji\n\* `Pacific\/Funafuti` - Pacific\/Funafuti\n\* `Pacific\/Galapagos` - Pacific\/Galapagos\n\* `Pacific\/Gambier` - Pacific\/Gambier\n\* `Pacific\/Guadalcanal` - Pacific\/Guadalcanal\n\* `Pacific\/Guam` - Pacific\/Guam\n\* `Pacific\/Honolulu` - Pacific\/Honolulu\n\* `Pacific\/Johnston` - Pacific\/Johnston\n\* `Pacific\/Kanton` - Pacific\/Kanton\n\* `Pacific\/Kiritimati` - Pacific\/Kiritimati\n\* `Pacific\/Kosrae` - Pacific\/Kosrae\n\* `Pacific\/Kwajalein` - Pacific\/Kwajalein\n\* `Pacific\/Majuro` - Pacific\/Majuro\n\* `Pacific\/Marquesas` - Pacific\/Marquesas\n\* `Pacific\/Midway` - Pacific\/Midway\n\* `Pacific\/Nauru` - Pacific\/Nauru\n\* `Pacific\/Niue` - Pacific\/Niue\n\* `Pacific\/Norfolk` - Pacific\/Norfolk\n\* `Pacific\/Noumea` - Pacific\/Noumea\n\* `Pacific\/Pago_Pago` - Pacific\/Pago_Pago\n\* `Pacific\/Palau` - Pacific\/Palau\n\* `Pacific\/Pitcairn` - Pacific\/Pitcairn\n\* `Pacific\/Pohnpei` - Pacific\/Pohnpei\n\* `Pacific\/Ponape` - Pacific\/Ponape\n\* `Pacific\/Port_Moresby` - Pacific\/Port_Moresby\n\* `Pacific\/Rarotonga` - Pacific\/Rarotonga\n\* `Pacific\/Saipan` - Pacific\/Saipan\n\* `Pacific\/Samoa` - Pacific\/Samoa\n\* `Pacific\/Tahiti` - Pacific\/Tahiti\n\* `Pacific\/Tarawa` - Pacific\/Tarawa\n\* `Pacific\/Tongatapu` - Pacific\/Tongatapu\n\* `Pacific\/Truk` - Pacific\/Truk\n\* `Pacific\/Wake` - Pacific\/Wake\n\* `Pacific\/Wallis` - Pacific\/Wallis\n\* `Pacific\/Yap` - Pacific\/Yap\n\* `Poland` - Poland\n\* `Portugal` - Portugal\n\* `ROC` - ROC\n\* `ROK` - ROK\n\* `Singapore` - Singapore\n\* `Turkey` - Turkey\n\* `UCT` - UCT\n\* `US\/Alaska` - US\/Alaska\n\* `US\/Aleutian` - US\/Aleutian\n\* `US\/Arizona` - US\/Arizona\n\* `US\/Central` - US\/Central\n\* `US\/East-Indiana` - US\/East-Indiana\n\* `US\/Eastern` - US\/Eastern\n\* `US\/Hawaii` - US\/Hawaii\n\* `US\/Indiana-Starke` - US\/Indiana-Starke\n\* `US\/Michigan` - US\/Michigan\n\* `US\/Mountain` - US\/Mountain\n\* `US\/Pacific` - US\/Pacific\n\* `US\/Samoa` - US\/Samoa\n\* `UTC` - UTC\n\* `Universal` - Universal\n\* `W-SU` - W-SU\n\* `WET` - WET\n\* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(organizationsProjectsResetTokenPartialUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat('decimal', organizationsProjectsResetTokenPartialUpdateBodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(organizationsProjectsResetTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(organizationsProjectsResetTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(organizationsProjectsResetTokenPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('\* `0` - Sunday\n\* `1` - Monday'),
                zod.null(),
            ])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n\* `0` - Sunday\n\* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(organizationsProjectsResetTokenPartialUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations \/ live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(
                        organizationsProjectsResetTokenPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax
                    )
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsResetTokenPartialUpdateBodyDefaultDataThemeMin)
            .max(organizationsProjectsResetTokenPartialUpdateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Projects for the current organization.
 */
export const organizationsProjectsRotateSecretTokenPartialUpdateBodyNameMax = 200

export const organizationsProjectsRotateSecretTokenPartialUpdateBodyProductDescriptionMax = 1000

export const organizationsProjectsRotateSecretTokenPartialUpdateBodyAppUrlsItemMax = 200

export const organizationsProjectsRotateSecretTokenPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const organizationsProjectsRotateSecretTokenPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const organizationsProjectsRotateSecretTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const organizationsProjectsRotateSecretTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const organizationsProjectsRotateSecretTokenPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const organizationsProjectsRotateSecretTokenPartialUpdateBodyRecordingDomainsItemMax = 200

export const organizationsProjectsRotateSecretTokenPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax = 90

export const organizationsProjectsRotateSecretTokenPartialUpdateBodyDefaultDataThemeMin = -2147483648
export const organizationsProjectsRotateSecretTokenPartialUpdateBodyDefaultDataThemeMax = 2147483647

export const OrganizationsProjectsRotateSecretTokenPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(organizationsProjectsRotateSecretTokenPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(organizationsProjectsRotateSecretTokenPartialUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(zod.string().max(organizationsProjectsRotateSecretTokenPartialUpdateBodyAppUrlsItemMax).nullable())
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal\/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal\/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .optional()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America\/Los_Angeles`).\n\n\* `Africa\/Abidjan` - Africa\/Abidjan\n\* `Africa\/Accra` - Africa\/Accra\n\* `Africa\/Addis_Ababa` - Africa\/Addis_Ababa\n\* `Africa\/Algiers` - Africa\/Algiers\n\* `Africa\/Asmara` - Africa\/Asmara\n\* `Africa\/Asmera` - Africa\/Asmera\n\* `Africa\/Bamako` - Africa\/Bamako\n\* `Africa\/Bangui` - Africa\/Bangui\n\* `Africa\/Banjul` - Africa\/Banjul\n\* `Africa\/Bissau` - Africa\/Bissau\n\* `Africa\/Blantyre` - Africa\/Blantyre\n\* `Africa\/Brazzaville` - Africa\/Brazzaville\n\* `Africa\/Bujumbura` - Africa\/Bujumbura\n\* `Africa\/Cairo` - Africa\/Cairo\n\* `Africa\/Casablanca` - Africa\/Casablanca\n\* `Africa\/Ceuta` - Africa\/Ceuta\n\* `Africa\/Conakry` - Africa\/Conakry\n\* `Africa\/Dakar` - Africa\/Dakar\n\* `Africa\/Dar_es_Salaam` - Africa\/Dar_es_Salaam\n\* `Africa\/Djibouti` - Africa\/Djibouti\n\* `Africa\/Douala` - Africa\/Douala\n\* `Africa\/El_Aaiun` - Africa\/El_Aaiun\n\* `Africa\/Freetown` - Africa\/Freetown\n\* `Africa\/Gaborone` - Africa\/Gaborone\n\* `Africa\/Harare` - Africa\/Harare\n\* `Africa\/Johannesburg` - Africa\/Johannesburg\n\* `Africa\/Juba` - Africa\/Juba\n\* `Africa\/Kampala` - Africa\/Kampala\n\* `Africa\/Khartoum` - Africa\/Khartoum\n\* `Africa\/Kigali` - Africa\/Kigali\n\* `Africa\/Kinshasa` - Africa\/Kinshasa\n\* `Africa\/Lagos` - Africa\/Lagos\n\* `Africa\/Libreville` - Africa\/Libreville\n\* `Africa\/Lome` - Africa\/Lome\n\* `Africa\/Luanda` - Africa\/Luanda\n\* `Africa\/Lubumbashi` - Africa\/Lubumbashi\n\* `Africa\/Lusaka` - Africa\/Lusaka\n\* `Africa\/Malabo` - Africa\/Malabo\n\* `Africa\/Maputo` - Africa\/Maputo\n\* `Africa\/Maseru` - Africa\/Maseru\n\* `Africa\/Mbabane` - Africa\/Mbabane\n\* `Africa\/Mogadishu` - Africa\/Mogadishu\n\* `Africa\/Monrovia` - Africa\/Monrovia\n\* `Africa\/Nairobi` - Africa\/Nairobi\n\* `Africa\/Ndjamena` - Africa\/Ndjamena\n\* `Africa\/Niamey` - Africa\/Niamey\n\* `Africa\/Nouakchott` - Africa\/Nouakchott\n\* `Africa\/Ouagadougou` - Africa\/Ouagadougou\n\* `Africa\/Porto-Novo` - Africa\/Porto-Novo\n\* `Africa\/Sao_Tome` - Africa\/Sao_Tome\n\* `Africa\/Timbuktu` - Africa\/Timbuktu\n\* `Africa\/Tripoli` - Africa\/Tripoli\n\* `Africa\/Tunis` - Africa\/Tunis\n\* `Africa\/Windhoek` - Africa\/Windhoek\n\* `America\/Adak` - America\/Adak\n\* `America\/Anchorage` - America\/Anchorage\n\* `America\/Anguilla` - America\/Anguilla\n\* `America\/Antigua` - America\/Antigua\n\* `America\/Araguaina` - America\/Araguaina\n\* `America\/Argentina\/Buenos_Aires` - America\/Argentina\/Buenos_Aires\n\* `America\/Argentina\/Catamarca` - America\/Argentina\/Catamarca\n\* `America\/Argentina\/ComodRivadavia` - America\/Argentina\/ComodRivadavia\n\* `America\/Argentina\/Cordoba` - America\/Argentina\/Cordoba\n\* `America\/Argentina\/Jujuy` - America\/Argentina\/Jujuy\n\* `America\/Argentina\/La_Rioja` - America\/Argentina\/La_Rioja\n\* `America\/Argentina\/Mendoza` - America\/Argentina\/Mendoza\n\* `America\/Argentina\/Rio_Gallegos` - America\/Argentina\/Rio_Gallegos\n\* `America\/Argentina\/Salta` - America\/Argentina\/Salta\n\* `America\/Argentina\/San_Juan` - America\/Argentina\/San_Juan\n\* `America\/Argentina\/San_Luis` - America\/Argentina\/San_Luis\n\* `America\/Argentina\/Tucuman` - America\/Argentina\/Tucuman\n\* `America\/Argentina\/Ushuaia` - America\/Argentina\/Ushuaia\n\* `America\/Aruba` - America\/Aruba\n\* `America\/Asuncion` - America\/Asuncion\n\* `America\/Atikokan` - America\/Atikokan\n\* `America\/Atka` - America\/Atka\n\* `America\/Bahia` - America\/Bahia\n\* `America\/Bahia_Banderas` - America\/Bahia_Banderas\n\* `America\/Barbados` - America\/Barbados\n\* `America\/Belem` - America\/Belem\n\* `America\/Belize` - America\/Belize\n\* `America\/Blanc-Sablon` - America\/Blanc-Sablon\n\* `America\/Boa_Vista` - America\/Boa_Vista\n\* `America\/Bogota` - America\/Bogota\n\* `America\/Boise` - America\/Boise\n\* `America\/Buenos_Aires` - America\/Buenos_Aires\n\* `America\/Cambridge_Bay` - America\/Cambridge_Bay\n\* `America\/Campo_Grande` - America\/Campo_Grande\n\* `America\/Cancun` - America\/Cancun\n\* `America\/Caracas` - America\/Caracas\n\* `America\/Catamarca` - America\/Catamarca\n\* `America\/Cayenne` - America\/Cayenne\n\* `America\/Cayman` - America\/Cayman\n\* `America\/Chicago` - America\/Chicago\n\* `America\/Chihuahua` - America\/Chihuahua\n\* `America\/Ciudad_Juarez` - America\/Ciudad_Juarez\n\* `America\/Coral_Harbour` - America\/Coral_Harbour\n\* `America\/Cordoba` - America\/Cordoba\n\* `America\/Costa_Rica` - America\/Costa_Rica\n\* `America\/Creston` - America\/Creston\n\* `America\/Cuiaba` - America\/Cuiaba\n\* `America\/Curacao` - America\/Curacao\n\* `America\/Danmarkshavn` - America\/Danmarkshavn\n\* `America\/Dawson` - America\/Dawson\n\* `America\/Dawson_Creek` - America\/Dawson_Creek\n\* `America\/Denver` - America\/Denver\n\* `America\/Detroit` - America\/Detroit\n\* `America\/Dominica` - America\/Dominica\n\* `America\/Edmonton` - America\/Edmonton\n\* `America\/Eirunepe` - America\/Eirunepe\n\* `America\/El_Salvador` - America\/El_Salvador\n\* `America\/Ensenada` - America\/Ensenada\n\* `America\/Fort_Nelson` - America\/Fort_Nelson\n\* `America\/Fort_Wayne` - America\/Fort_Wayne\n\* `America\/Fortaleza` - America\/Fortaleza\n\* `America\/Glace_Bay` - America\/Glace_Bay\n\* `America\/Godthab` - America\/Godthab\n\* `America\/Goose_Bay` - America\/Goose_Bay\n\* `America\/Grand_Turk` - America\/Grand_Turk\n\* `America\/Grenada` - America\/Grenada\n\* `America\/Guadeloupe` - America\/Guadeloupe\n\* `America\/Guatemala` - America\/Guatemala\n\* `America\/Guayaquil` - America\/Guayaquil\n\* `America\/Guyana` - America\/Guyana\n\* `America\/Halifax` - America\/Halifax\n\* `America\/Havana` - America\/Havana\n\* `America\/Hermosillo` - America\/Hermosillo\n\* `America\/Indiana\/Indianapolis` - America\/Indiana\/Indianapolis\n\* `America\/Indiana\/Knox` - America\/Indiana\/Knox\n\* `America\/Indiana\/Marengo` - America\/Indiana\/Marengo\n\* `America\/Indiana\/Petersburg` - America\/Indiana\/Petersburg\n\* `America\/Indiana\/Tell_City` - America\/Indiana\/Tell_City\n\* `America\/Indiana\/Vevay` - America\/Indiana\/Vevay\n\* `America\/Indiana\/Vincennes` - America\/Indiana\/Vincennes\n\* `America\/Indiana\/Winamac` - America\/Indiana\/Winamac\n\* `America\/Indianapolis` - America\/Indianapolis\n\* `America\/Inuvik` - America\/Inuvik\n\* `America\/Iqaluit` - America\/Iqaluit\n\* `America\/Jamaica` - America\/Jamaica\n\* `America\/Jujuy` - America\/Jujuy\n\* `America\/Juneau` - America\/Juneau\n\* `America\/Kentucky\/Louisville` - America\/Kentucky\/Louisville\n\* `America\/Kentucky\/Monticello` - America\/Kentucky\/Monticello\n\* `America\/Knox_IN` - America\/Knox_IN\n\* `America\/Kralendijk` - America\/Kralendijk\n\* `America\/La_Paz` - America\/La_Paz\n\* `America\/Lima` - America\/Lima\n\* `America\/Los_Angeles` - America\/Los_Angeles\n\* `America\/Louisville` - America\/Louisville\n\* `America\/Lower_Princes` - America\/Lower_Princes\n\* `America\/Maceio` - America\/Maceio\n\* `America\/Managua` - America\/Managua\n\* `America\/Manaus` - America\/Manaus\n\* `America\/Marigot` - America\/Marigot\n\* `America\/Martinique` - America\/Martinique\n\* `America\/Matamoros` - America\/Matamoros\n\* `America\/Mazatlan` - America\/Mazatlan\n\* `America\/Mendoza` - America\/Mendoza\n\* `America\/Menominee` - America\/Menominee\n\* `America\/Merida` - America\/Merida\n\* `America\/Metlakatla` - America\/Metlakatla\n\* `America\/Mexico_City` - America\/Mexico_City\n\* `America\/Miquelon` - America\/Miquelon\n\* `America\/Moncton` - America\/Moncton\n\* `America\/Monterrey` - America\/Monterrey\n\* `America\/Montevideo` - America\/Montevideo\n\* `America\/Montreal` - America\/Montreal\n\* `America\/Montserrat` - America\/Montserrat\n\* `America\/Nassau` - America\/Nassau\n\* `America\/New_York` - America\/New_York\n\* `America\/Nipigon` - America\/Nipigon\n\* `America\/Nome` - America\/Nome\n\* `America\/Noronha` - America\/Noronha\n\* `America\/North_Dakota\/Beulah` - America\/North_Dakota\/Beulah\n\* `America\/North_Dakota\/Center` - America\/North_Dakota\/Center\n\* `America\/North_Dakota\/New_Salem` - America\/North_Dakota\/New_Salem\n\* `America\/Nuuk` - America\/Nuuk\n\* `America\/Ojinaga` - America\/Ojinaga\n\* `America\/Panama` - America\/Panama\n\* `America\/Pangnirtung` - America\/Pangnirtung\n\* `America\/Paramaribo` - America\/Paramaribo\n\* `America\/Phoenix` - America\/Phoenix\n\* `America\/Port-au-Prince` - America\/Port-au-Prince\n\* `America\/Port_of_Spain` - America\/Port_of_Spain\n\* `America\/Porto_Acre` - America\/Porto_Acre\n\* `America\/Porto_Velho` - America\/Porto_Velho\n\* `America\/Puerto_Rico` - America\/Puerto_Rico\n\* `America\/Punta_Arenas` - America\/Punta_Arenas\n\* `America\/Rainy_River` - America\/Rainy_River\n\* `America\/Rankin_Inlet` - America\/Rankin_Inlet\n\* `America\/Recife` - America\/Recife\n\* `America\/Regina` - America\/Regina\n\* `America\/Resolute` - America\/Resolute\n\* `America\/Rio_Branco` - America\/Rio_Branco\n\* `America\/Rosario` - America\/Rosario\n\* `America\/Santa_Isabel` - America\/Santa_Isabel\n\* `America\/Santarem` - America\/Santarem\n\* `America\/Santiago` - America\/Santiago\n\* `America\/Santo_Domingo` - America\/Santo_Domingo\n\* `America\/Sao_Paulo` - America\/Sao_Paulo\n\* `America\/Scoresbysund` - America\/Scoresbysund\n\* `America\/Shiprock` - America\/Shiprock\n\* `America\/Sitka` - America\/Sitka\n\* `America\/St_Barthelemy` - America\/St_Barthelemy\n\* `America\/St_Johns` - America\/St_Johns\n\* `America\/St_Kitts` - America\/St_Kitts\n\* `America\/St_Lucia` - America\/St_Lucia\n\* `America\/St_Thomas` - America\/St_Thomas\n\* `America\/St_Vincent` - America\/St_Vincent\n\* `America\/Swift_Current` - America\/Swift_Current\n\* `America\/Tegucigalpa` - America\/Tegucigalpa\n\* `America\/Thule` - America\/Thule\n\* `America\/Thunder_Bay` - America\/Thunder_Bay\n\* `America\/Tijuana` - America\/Tijuana\n\* `America\/Toronto` - America\/Toronto\n\* `America\/Tortola` - America\/Tortola\n\* `America\/Vancouver` - America\/Vancouver\n\* `America\/Virgin` - America\/Virgin\n\* `America\/Whitehorse` - America\/Whitehorse\n\* `America\/Winnipeg` - America\/Winnipeg\n\* `America\/Yakutat` - America\/Yakutat\n\* `America\/Yellowknife` - America\/Yellowknife\n\* `Antarctica\/Casey` - Antarctica\/Casey\n\* `Antarctica\/Davis` - Antarctica\/Davis\n\* `Antarctica\/DumontDUrville` - Antarctica\/DumontDUrville\n\* `Antarctica\/Macquarie` - Antarctica\/Macquarie\n\* `Antarctica\/Mawson` - Antarctica\/Mawson\n\* `Antarctica\/McMurdo` - Antarctica\/McMurdo\n\* `Antarctica\/Palmer` - Antarctica\/Palmer\n\* `Antarctica\/Rothera` - Antarctica\/Rothera\n\* `Antarctica\/South_Pole` - Antarctica\/South_Pole\n\* `Antarctica\/Syowa` - Antarctica\/Syowa\n\* `Antarctica\/Troll` - Antarctica\/Troll\n\* `Antarctica\/Vostok` - Antarctica\/Vostok\n\* `Arctic\/Longyearbyen` - Arctic\/Longyearbyen\n\* `Asia\/Aden` - Asia\/Aden\n\* `Asia\/Almaty` - Asia\/Almaty\n\* `Asia\/Amman` - Asia\/Amman\n\* `Asia\/Anadyr` - Asia\/Anadyr\n\* `Asia\/Aqtau` - Asia\/Aqtau\n\* `Asia\/Aqtobe` - Asia\/Aqtobe\n\* `Asia\/Ashgabat` - Asia\/Ashgabat\n\* `Asia\/Ashkhabad` - Asia\/Ashkhabad\n\* `Asia\/Atyrau` - Asia\/Atyrau\n\* `Asia\/Baghdad` - Asia\/Baghdad\n\* `Asia\/Bahrain` - Asia\/Bahrain\n\* `Asia\/Baku` - Asia\/Baku\n\* `Asia\/Bangkok` - Asia\/Bangkok\n\* `Asia\/Barnaul` - Asia\/Barnaul\n\* `Asia\/Beirut` - Asia\/Beirut\n\* `Asia\/Bishkek` - Asia\/Bishkek\n\* `Asia\/Brunei` - Asia\/Brunei\n\* `Asia\/Calcutta` - Asia\/Calcutta\n\* `Asia\/Chita` - Asia\/Chita\n\* `Asia\/Choibalsan` - Asia\/Choibalsan\n\* `Asia\/Chongqing` - Asia\/Chongqing\n\* `Asia\/Chungking` - Asia\/Chungking\n\* `Asia\/Colombo` - Asia\/Colombo\n\* `Asia\/Dacca` - Asia\/Dacca\n\* `Asia\/Damascus` - Asia\/Damascus\n\* `Asia\/Dhaka` - Asia\/Dhaka\n\* `Asia\/Dili` - Asia\/Dili\n\* `Asia\/Dubai` - Asia\/Dubai\n\* `Asia\/Dushanbe` - Asia\/Dushanbe\n\* `Asia\/Famagusta` - Asia\/Famagusta\n\* `Asia\/Gaza` - Asia\/Gaza\n\* `Asia\/Harbin` - Asia\/Harbin\n\* `Asia\/Hebron` - Asia\/Hebron\n\* `Asia\/Ho_Chi_Minh` - Asia\/Ho_Chi_Minh\n\* `Asia\/Hong_Kong` - Asia\/Hong_Kong\n\* `Asia\/Hovd` - Asia\/Hovd\n\* `Asia\/Irkutsk` - Asia\/Irkutsk\n\* `Asia\/Istanbul` - Asia\/Istanbul\n\* `Asia\/Jakarta` - Asia\/Jakarta\n\* `Asia\/Jayapura` - Asia\/Jayapura\n\* `Asia\/Jerusalem` - Asia\/Jerusalem\n\* `Asia\/Kabul` - Asia\/Kabul\n\* `Asia\/Kamchatka` - Asia\/Kamchatka\n\* `Asia\/Karachi` - Asia\/Karachi\n\* `Asia\/Kashgar` - Asia\/Kashgar\n\* `Asia\/Kathmandu` - Asia\/Kathmandu\n\* `Asia\/Katmandu` - Asia\/Katmandu\n\* `Asia\/Khandyga` - Asia\/Khandyga\n\* `Asia\/Kolkata` - Asia\/Kolkata\n\* `Asia\/Krasnoyarsk` - Asia\/Krasnoyarsk\n\* `Asia\/Kuala_Lumpur` - Asia\/Kuala_Lumpur\n\* `Asia\/Kuching` - Asia\/Kuching\n\* `Asia\/Kuwait` - Asia\/Kuwait\n\* `Asia\/Macao` - Asia\/Macao\n\* `Asia\/Macau` - Asia\/Macau\n\* `Asia\/Magadan` - Asia\/Magadan\n\* `Asia\/Makassar` - Asia\/Makassar\n\* `Asia\/Manila` - Asia\/Manila\n\* `Asia\/Muscat` - Asia\/Muscat\n\* `Asia\/Nicosia` - Asia\/Nicosia\n\* `Asia\/Novokuznetsk` - Asia\/Novokuznetsk\n\* `Asia\/Novosibirsk` - Asia\/Novosibirsk\n\* `Asia\/Omsk` - Asia\/Omsk\n\* `Asia\/Oral` - Asia\/Oral\n\* `Asia\/Phnom_Penh` - Asia\/Phnom_Penh\n\* `Asia\/Pontianak` - Asia\/Pontianak\n\* `Asia\/Pyongyang` - Asia\/Pyongyang\n\* `Asia\/Qatar` - Asia\/Qatar\n\* `Asia\/Qostanay` - Asia\/Qostanay\n\* `Asia\/Qyzylorda` - Asia\/Qyzylorda\n\* `Asia\/Rangoon` - Asia\/Rangoon\n\* `Asia\/Riyadh` - Asia\/Riyadh\n\* `Asia\/Saigon` - Asia\/Saigon\n\* `Asia\/Sakhalin` - Asia\/Sakhalin\n\* `Asia\/Samarkand` - Asia\/Samarkand\n\* `Asia\/Seoul` - Asia\/Seoul\n\* `Asia\/Shanghai` - Asia\/Shanghai\n\* `Asia\/Singapore` - Asia\/Singapore\n\* `Asia\/Srednekolymsk` - Asia\/Srednekolymsk\n\* `Asia\/Taipei` - Asia\/Taipei\n\* `Asia\/Tashkent` - Asia\/Tashkent\n\* `Asia\/Tbilisi` - Asia\/Tbilisi\n\* `Asia\/Tehran` - Asia\/Tehran\n\* `Asia\/Tel_Aviv` - Asia\/Tel_Aviv\n\* `Asia\/Thimbu` - Asia\/Thimbu\n\* `Asia\/Thimphu` - Asia\/Thimphu\n\* `Asia\/Tokyo` - Asia\/Tokyo\n\* `Asia\/Tomsk` - Asia\/Tomsk\n\* `Asia\/Ujung_Pandang` - Asia\/Ujung_Pandang\n\* `Asia\/Ulaanbaatar` - Asia\/Ulaanbaatar\n\* `Asia\/Ulan_Bator` - Asia\/Ulan_Bator\n\* `Asia\/Urumqi` - Asia\/Urumqi\n\* `Asia\/Ust-Nera` - Asia\/Ust-Nera\n\* `Asia\/Vientiane` - Asia\/Vientiane\n\* `Asia\/Vladivostok` - Asia\/Vladivostok\n\* `Asia\/Yakutsk` - Asia\/Yakutsk\n\* `Asia\/Yangon` - Asia\/Yangon\n\* `Asia\/Yekaterinburg` - Asia\/Yekaterinburg\n\* `Asia\/Yerevan` - Asia\/Yerevan\n\* `Atlantic\/Azores` - Atlantic\/Azores\n\* `Atlantic\/Bermuda` - Atlantic\/Bermuda\n\* `Atlantic\/Canary` - Atlantic\/Canary\n\* `Atlantic\/Cape_Verde` - Atlantic\/Cape_Verde\n\* `Atlantic\/Faeroe` - Atlantic\/Faeroe\n\* `Atlantic\/Faroe` - Atlantic\/Faroe\n\* `Atlantic\/Jan_Mayen` - Atlantic\/Jan_Mayen\n\* `Atlantic\/Madeira` - Atlantic\/Madeira\n\* `Atlantic\/Reykjavik` - Atlantic\/Reykjavik\n\* `Atlantic\/South_Georgia` - Atlantic\/South_Georgia\n\* `Atlantic\/St_Helena` - Atlantic\/St_Helena\n\* `Atlantic\/Stanley` - Atlantic\/Stanley\n\* `Australia\/ACT` - Australia\/ACT\n\* `Australia\/Adelaide` - Australia\/Adelaide\n\* `Australia\/Brisbane` - Australia\/Brisbane\n\* `Australia\/Broken_Hill` - Australia\/Broken_Hill\n\* `Australia\/Canberra` - Australia\/Canberra\n\* `Australia\/Currie` - Australia\/Currie\n\* `Australia\/Darwin` - Australia\/Darwin\n\* `Australia\/Eucla` - Australia\/Eucla\n\* `Australia\/Hobart` - Australia\/Hobart\n\* `Australia\/LHI` - Australia\/LHI\n\* `Australia\/Lindeman` - Australia\/Lindeman\n\* `Australia\/Lord_Howe` - Australia\/Lord_Howe\n\* `Australia\/Melbourne` - Australia\/Melbourne\n\* `Australia\/NSW` - Australia\/NSW\n\* `Australia\/North` - Australia\/North\n\* `Australia\/Perth` - Australia\/Perth\n\* `Australia\/Queensland` - Australia\/Queensland\n\* `Australia\/South` - Australia\/South\n\* `Australia\/Sydney` - Australia\/Sydney\n\* `Australia\/Tasmania` - Australia\/Tasmania\n\* `Australia\/Victoria` - Australia\/Victoria\n\* `Australia\/West` - Australia\/West\n\* `Australia\/Yancowinna` - Australia\/Yancowinna\n\* `Brazil\/Acre` - Brazil\/Acre\n\* `Brazil\/DeNoronha` - Brazil\/DeNoronha\n\* `Brazil\/East` - Brazil\/East\n\* `Brazil\/West` - Brazil\/West\n\* `CET` - CET\n\* `CST6CDT` - CST6CDT\n\* `Canada\/Atlantic` - Canada\/Atlantic\n\* `Canada\/Central` - Canada\/Central\n\* `Canada\/Eastern` - Canada\/Eastern\n\* `Canada\/Mountain` - Canada\/Mountain\n\* `Canada\/Newfoundland` - Canada\/Newfoundland\n\* `Canada\/Pacific` - Canada\/Pacific\n\* `Canada\/Saskatchewan` - Canada\/Saskatchewan\n\* `Canada\/Yukon` - Canada\/Yukon\n\* `Chile\/Continental` - Chile\/Continental\n\* `Chile\/EasterIsland` - Chile\/EasterIsland\n\* `Cuba` - Cuba\n\* `EET` - EET\n\* `EST` - EST\n\* `EST5EDT` - EST5EDT\n\* `Egypt` - Egypt\n\* `Eire` - Eire\n\* `Etc\/GMT` - Etc\/GMT\n\* `Etc\/GMT+0` - Etc\/GMT+0\n\* `Etc\/GMT+1` - Etc\/GMT+1\n\* `Etc\/GMT+10` - Etc\/GMT+10\n\* `Etc\/GMT+11` - Etc\/GMT+11\n\* `Etc\/GMT+12` - Etc\/GMT+12\n\* `Etc\/GMT+2` - Etc\/GMT+2\n\* `Etc\/GMT+3` - Etc\/GMT+3\n\* `Etc\/GMT+4` - Etc\/GMT+4\n\* `Etc\/GMT+5` - Etc\/GMT+5\n\* `Etc\/GMT+6` - Etc\/GMT+6\n\* `Etc\/GMT+7` - Etc\/GMT+7\n\* `Etc\/GMT+8` - Etc\/GMT+8\n\* `Etc\/GMT+9` - Etc\/GMT+9\n\* `Etc\/GMT-0` - Etc\/GMT-0\n\* `Etc\/GMT-1` - Etc\/GMT-1\n\* `Etc\/GMT-10` - Etc\/GMT-10\n\* `Etc\/GMT-11` - Etc\/GMT-11\n\* `Etc\/GMT-12` - Etc\/GMT-12\n\* `Etc\/GMT-13` - Etc\/GMT-13\n\* `Etc\/GMT-14` - Etc\/GMT-14\n\* `Etc\/GMT-2` - Etc\/GMT-2\n\* `Etc\/GMT-3` - Etc\/GMT-3\n\* `Etc\/GMT-4` - Etc\/GMT-4\n\* `Etc\/GMT-5` - Etc\/GMT-5\n\* `Etc\/GMT-6` - Etc\/GMT-6\n\* `Etc\/GMT-7` - Etc\/GMT-7\n\* `Etc\/GMT-8` - Etc\/GMT-8\n\* `Etc\/GMT-9` - Etc\/GMT-9\n\* `Etc\/GMT0` - Etc\/GMT0\n\* `Etc\/Greenwich` - Etc\/Greenwich\n\* `Etc\/UCT` - Etc\/UCT\n\* `Etc\/UTC` - Etc\/UTC\n\* `Etc\/Universal` - Etc\/Universal\n\* `Etc\/Zulu` - Etc\/Zulu\n\* `Europe\/Amsterdam` - Europe\/Amsterdam\n\* `Europe\/Andorra` - Europe\/Andorra\n\* `Europe\/Astrakhan` - Europe\/Astrakhan\n\* `Europe\/Athens` - Europe\/Athens\n\* `Europe\/Belfast` - Europe\/Belfast\n\* `Europe\/Belgrade` - Europe\/Belgrade\n\* `Europe\/Berlin` - Europe\/Berlin\n\* `Europe\/Bratislava` - Europe\/Bratislava\n\* `Europe\/Brussels` - Europe\/Brussels\n\* `Europe\/Bucharest` - Europe\/Bucharest\n\* `Europe\/Budapest` - Europe\/Budapest\n\* `Europe\/Busingen` - Europe\/Busingen\n\* `Europe\/Chisinau` - Europe\/Chisinau\n\* `Europe\/Copenhagen` - Europe\/Copenhagen\n\* `Europe\/Dublin` - Europe\/Dublin\n\* `Europe\/Gibraltar` - Europe\/Gibraltar\n\* `Europe\/Guernsey` - Europe\/Guernsey\n\* `Europe\/Helsinki` - Europe\/Helsinki\n\* `Europe\/Isle_of_Man` - Europe\/Isle_of_Man\n\* `Europe\/Istanbul` - Europe\/Istanbul\n\* `Europe\/Jersey` - Europe\/Jersey\n\* `Europe\/Kaliningrad` - Europe\/Kaliningrad\n\* `Europe\/Kiev` - Europe\/Kiev\n\* `Europe\/Kirov` - Europe\/Kirov\n\* `Europe\/Kyiv` - Europe\/Kyiv\n\* `Europe\/Lisbon` - Europe\/Lisbon\n\* `Europe\/Ljubljana` - Europe\/Ljubljana\n\* `Europe\/London` - Europe\/London\n\* `Europe\/Luxembourg` - Europe\/Luxembourg\n\* `Europe\/Madrid` - Europe\/Madrid\n\* `Europe\/Malta` - Europe\/Malta\n\* `Europe\/Mariehamn` - Europe\/Mariehamn\n\* `Europe\/Minsk` - Europe\/Minsk\n\* `Europe\/Monaco` - Europe\/Monaco\n\* `Europe\/Moscow` - Europe\/Moscow\n\* `Europe\/Nicosia` - Europe\/Nicosia\n\* `Europe\/Oslo` - Europe\/Oslo\n\* `Europe\/Paris` - Europe\/Paris\n\* `Europe\/Podgorica` - Europe\/Podgorica\n\* `Europe\/Prague` - Europe\/Prague\n\* `Europe\/Riga` - Europe\/Riga\n\* `Europe\/Rome` - Europe\/Rome\n\* `Europe\/Samara` - Europe\/Samara\n\* `Europe\/San_Marino` - Europe\/San_Marino\n\* `Europe\/Sarajevo` - Europe\/Sarajevo\n\* `Europe\/Saratov` - Europe\/Saratov\n\* `Europe\/Simferopol` - Europe\/Simferopol\n\* `Europe\/Skopje` - Europe\/Skopje\n\* `Europe\/Sofia` - Europe\/Sofia\n\* `Europe\/Stockholm` - Europe\/Stockholm\n\* `Europe\/Tallinn` - Europe\/Tallinn\n\* `Europe\/Tirane` - Europe\/Tirane\n\* `Europe\/Tiraspol` - Europe\/Tiraspol\n\* `Europe\/Ulyanovsk` - Europe\/Ulyanovsk\n\* `Europe\/Uzhgorod` - Europe\/Uzhgorod\n\* `Europe\/Vaduz` - Europe\/Vaduz\n\* `Europe\/Vatican` - Europe\/Vatican\n\* `Europe\/Vienna` - Europe\/Vienna\n\* `Europe\/Vilnius` - Europe\/Vilnius\n\* `Europe\/Volgograd` - Europe\/Volgograd\n\* `Europe\/Warsaw` - Europe\/Warsaw\n\* `Europe\/Zagreb` - Europe\/Zagreb\n\* `Europe\/Zaporozhye` - Europe\/Zaporozhye\n\* `Europe\/Zurich` - Europe\/Zurich\n\* `GB` - GB\n\* `GB-Eire` - GB-Eire\n\* `GMT` - GMT\n\* `GMT+0` - GMT+0\n\* `GMT-0` - GMT-0\n\* `GMT0` - GMT0\n\* `Greenwich` - Greenwich\n\* `HST` - HST\n\* `Hongkong` - Hongkong\n\* `Iceland` - Iceland\n\* `Indian\/Antananarivo` - Indian\/Antananarivo\n\* `Indian\/Chagos` - Indian\/Chagos\n\* `Indian\/Christmas` - Indian\/Christmas\n\* `Indian\/Cocos` - Indian\/Cocos\n\* `Indian\/Comoro` - Indian\/Comoro\n\* `Indian\/Kerguelen` - Indian\/Kerguelen\n\* `Indian\/Mahe` - Indian\/Mahe\n\* `Indian\/Maldives` - Indian\/Maldives\n\* `Indian\/Mauritius` - Indian\/Mauritius\n\* `Indian\/Mayotte` - Indian\/Mayotte\n\* `Indian\/Reunion` - Indian\/Reunion\n\* `Iran` - Iran\n\* `Israel` - Israel\n\* `Jamaica` - Jamaica\n\* `Japan` - Japan\n\* `Kwajalein` - Kwajalein\n\* `Libya` - Libya\n\* `MET` - MET\n\* `MST` - MST\n\* `MST7MDT` - MST7MDT\n\* `Mexico\/BajaNorte` - Mexico\/BajaNorte\n\* `Mexico\/BajaSur` - Mexico\/BajaSur\n\* `Mexico\/General` - Mexico\/General\n\* `NZ` - NZ\n\* `NZ-CHAT` - NZ-CHAT\n\* `Navajo` - Navajo\n\* `PRC` - PRC\n\* `PST8PDT` - PST8PDT\n\* `Pacific\/Apia` - Pacific\/Apia\n\* `Pacific\/Auckland` - Pacific\/Auckland\n\* `Pacific\/Bougainville` - Pacific\/Bougainville\n\* `Pacific\/Chatham` - Pacific\/Chatham\n\* `Pacific\/Chuuk` - Pacific\/Chuuk\n\* `Pacific\/Easter` - Pacific\/Easter\n\* `Pacific\/Efate` - Pacific\/Efate\n\* `Pacific\/Enderbury` - Pacific\/Enderbury\n\* `Pacific\/Fakaofo` - Pacific\/Fakaofo\n\* `Pacific\/Fiji` - Pacific\/Fiji\n\* `Pacific\/Funafuti` - Pacific\/Funafuti\n\* `Pacific\/Galapagos` - Pacific\/Galapagos\n\* `Pacific\/Gambier` - Pacific\/Gambier\n\* `Pacific\/Guadalcanal` - Pacific\/Guadalcanal\n\* `Pacific\/Guam` - Pacific\/Guam\n\* `Pacific\/Honolulu` - Pacific\/Honolulu\n\* `Pacific\/Johnston` - Pacific\/Johnston\n\* `Pacific\/Kanton` - Pacific\/Kanton\n\* `Pacific\/Kiritimati` - Pacific\/Kiritimati\n\* `Pacific\/Kosrae` - Pacific\/Kosrae\n\* `Pacific\/Kwajalein` - Pacific\/Kwajalein\n\* `Pacific\/Majuro` - Pacific\/Majuro\n\* `Pacific\/Marquesas` - Pacific\/Marquesas\n\* `Pacific\/Midway` - Pacific\/Midway\n\* `Pacific\/Nauru` - Pacific\/Nauru\n\* `Pacific\/Niue` - Pacific\/Niue\n\* `Pacific\/Norfolk` - Pacific\/Norfolk\n\* `Pacific\/Noumea` - Pacific\/Noumea\n\* `Pacific\/Pago_Pago` - Pacific\/Pago_Pago\n\* `Pacific\/Palau` - Pacific\/Palau\n\* `Pacific\/Pitcairn` - Pacific\/Pitcairn\n\* `Pacific\/Pohnpei` - Pacific\/Pohnpei\n\* `Pacific\/Ponape` - Pacific\/Ponape\n\* `Pacific\/Port_Moresby` - Pacific\/Port_Moresby\n\* `Pacific\/Rarotonga` - Pacific\/Rarotonga\n\* `Pacific\/Saipan` - Pacific\/Saipan\n\* `Pacific\/Samoa` - Pacific\/Samoa\n\* `Pacific\/Tahiti` - Pacific\/Tahiti\n\* `Pacific\/Tarawa` - Pacific\/Tarawa\n\* `Pacific\/Tongatapu` - Pacific\/Tongatapu\n\* `Pacific\/Truk` - Pacific\/Truk\n\* `Pacific\/Wake` - Pacific\/Wake\n\* `Pacific\/Wallis` - Pacific\/Wallis\n\* `Pacific\/Yap` - Pacific\/Yap\n\* `Poland` - Poland\n\* `Portugal` - Portugal\n\* `ROC` - ROC\n\* `ROK` - ROK\n\* `Singapore` - Singapore\n\* `Turkey` - Turkey\n\* `UCT` - UCT\n\* `US\/Alaska` - US\/Alaska\n\* `US\/Aleutian` - US\/Aleutian\n\* `US\/Arizona` - US\/Arizona\n\* `US\/Central` - US\/Central\n\* `US\/East-Indiana` - US\/East-Indiana\n\* `US\/Eastern` - US\/Eastern\n\* `US\/Hawaii` - US\/Hawaii\n\* `US\/Indiana-Starke` - US\/Indiana-Starke\n\* `US\/Michigan` - US\/Michigan\n\* `US\/Mountain` - US\/Mountain\n\* `US\/Pacific` - US\/Pacific\n\* `US\/Samoa` - US\/Samoa\n\* `UTC` - UTC\n\* `Universal` - Universal\n\* `W-SU` - W-SU\n\* `WET` - WET\n\* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsRotateSecretTokenPartialUpdateBodyPersonDisplayNamePropertiesItemMax)
            )
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().optional(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().optional(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().optional(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .stringFormat(
                'decimal',
                organizationsProjectsRotateSecretTokenPartialUpdateBodySessionRecordingSampleRateRegExp
            )
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(organizationsProjectsRotateSecretTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(organizationsProjectsRotateSecretTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().optional(),
        session_recording_network_payload_capture_config: zod.unknown().optional(),
        session_recording_masking_config: zod.unknown().optional(),
        session_recording_url_trigger_config: zod.array(zod.unknown()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(organizationsProjectsRotateSecretTokenPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('\* `0` - Sunday\n\* `1` - Monday'),
                zod.null(),
            ])
            .optional()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n\* `0` - Sunday\n\* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(
                zod
                    .string()
                    .max(organizationsProjectsRotateSecretTokenPartialUpdateBodyRecordingDomainsItemMax)
                    .nullable()
            )
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations \/ live chat product for this project.'),
        conversations_settings: zod.unknown().optional(),
        logs_settings: zod.unknown().optional(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        revenue_analytics_config: zod
            .object({
                base_currency: zod
                    .enum([
                        'AED',
                        'AFN',
                        'ALL',
                        'AMD',
                        'ANG',
                        'AOA',
                        'ARS',
                        'AUD',
                        'AWG',
                        'AZN',
                        'BAM',
                        'BBD',
                        'BDT',
                        'BGN',
                        'BHD',
                        'BIF',
                        'BMD',
                        'BND',
                        'BOB',
                        'BRL',
                        'BSD',
                        'BTC',
                        'BTN',
                        'BWP',
                        'BYN',
                        'BZD',
                        'CAD',
                        'CDF',
                        'CHF',
                        'CLP',
                        'CNY',
                        'COP',
                        'CRC',
                        'CVE',
                        'CZK',
                        'DJF',
                        'DKK',
                        'DOP',
                        'DZD',
                        'EGP',
                        'ERN',
                        'ETB',
                        'EUR',
                        'FJD',
                        'GBP',
                        'GEL',
                        'GHS',
                        'GIP',
                        'GMD',
                        'GNF',
                        'GTQ',
                        'GYD',
                        'HKD',
                        'HNL',
                        'HRK',
                        'HTG',
                        'HUF',
                        'IDR',
                        'ILS',
                        'INR',
                        'IQD',
                        'IRR',
                        'ISK',
                        'JMD',
                        'JOD',
                        'JPY',
                        'KES',
                        'KGS',
                        'KHR',
                        'KMF',
                        'KRW',
                        'KWD',
                        'KYD',
                        'KZT',
                        'LAK',
                        'LBP',
                        'LKR',
                        'LRD',
                        'LTL',
                        'LVL',
                        'LSL',
                        'LYD',
                        'MAD',
                        'MDL',
                        'MGA',
                        'MKD',
                        'MMK',
                        'MNT',
                        'MOP',
                        'MRU',
                        'MTL',
                        'MUR',
                        'MVR',
                        'MWK',
                        'MXN',
                        'MYR',
                        'MZN',
                        'NAD',
                        'NGN',
                        'NIO',
                        'NOK',
                        'NPR',
                        'NZD',
                        'OMR',
                        'PAB',
                        'PEN',
                        'PGK',
                        'PHP',
                        'PKR',
                        'PLN',
                        'PYG',
                        'QAR',
                        'RON',
                        'RSD',
                        'RUB',
                        'RWF',
                        'SAR',
                        'SBD',
                        'SCR',
                        'SDG',
                        'SEK',
                        'SGD',
                        'SRD',
                        'SSP',
                        'STN',
                        'SYP',
                        'SZL',
                        'THB',
                        'TJS',
                        'TMT',
                        'TND',
                        'TOP',
                        'TRY',
                        'TTD',
                        'TWD',
                        'TZS',
                        'UAH',
                        'UGX',
                        'USD',
                        'UYU',
                        'UZS',
                        'VES',
                        'VND',
                        'VUV',
                        'WST',
                        'XAF',
                        'XCD',
                        'XOF',
                        'XPF',
                        'YER',
                        'ZAR',
                        'ZMW',
                    ])
                    .optional()
                    .describe(
                        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
                    ),
                events: zod.unknown().optional(),
                goals: zod.unknown().optional(),
                filter_test_accounts: zod.boolean().optional(),
            })
            .optional(),
        marketing_analytics_config: zod
            .object({
                sources_map: zod.unknown().optional(),
                conversion_goals: zod.unknown().optional(),
                attribution_window_days: zod
                    .number()
                    .min(1)
                    .max(
                        organizationsProjectsRotateSecretTokenPartialUpdateBodyMarketingAnalyticsConfigAttributionWindowDaysMax
                    )
                    .optional(),
                attribution_mode: zod
                    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
                    .optional()
                    .describe(
                        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
                    ),
                campaign_name_mappings: zod.unknown().optional(),
                custom_source_mappings: zod.unknown().optional(),
                campaign_field_preferences: zod.unknown().optional(),
            })
            .optional(),
        customer_analytics_config: zod
            .object({
                activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
                signup_pageview_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count signup pageviews on dashboards.'),
                signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
                subscription_event: zod
                    .unknown()
                    .optional()
                    .describe('Event used to count subscriptions on dashboards.'),
                payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
                account_group_type_index: zod
                    .number()
                    .nullish()
                    .describe(
                        'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
                    ),
            })
            .optional(),
        workflows_config: zod
            .object({
                capture_workflows_engagement_events: zod
                    .boolean()
                    .optional()
                    .describe(
                        'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
                    ),
            })
            .optional(),
        base_currency: zod
            .enum([
                'AED',
                'AFN',
                'ALL',
                'AMD',
                'ANG',
                'AOA',
                'ARS',
                'AUD',
                'AWG',
                'AZN',
                'BAM',
                'BBD',
                'BDT',
                'BGN',
                'BHD',
                'BIF',
                'BMD',
                'BND',
                'BOB',
                'BRL',
                'BSD',
                'BTC',
                'BTN',
                'BWP',
                'BYN',
                'BZD',
                'CAD',
                'CDF',
                'CHF',
                'CLP',
                'CNY',
                'COP',
                'CRC',
                'CVE',
                'CZK',
                'DJF',
                'DKK',
                'DOP',
                'DZD',
                'EGP',
                'ERN',
                'ETB',
                'EUR',
                'FJD',
                'GBP',
                'GEL',
                'GHS',
                'GIP',
                'GMD',
                'GNF',
                'GTQ',
                'GYD',
                'HKD',
                'HNL',
                'HRK',
                'HTG',
                'HUF',
                'IDR',
                'ILS',
                'INR',
                'IQD',
                'IRR',
                'ISK',
                'JMD',
                'JOD',
                'JPY',
                'KES',
                'KGS',
                'KHR',
                'KMF',
                'KRW',
                'KWD',
                'KYD',
                'KZT',
                'LAK',
                'LBP',
                'LKR',
                'LRD',
                'LTL',
                'LVL',
                'LSL',
                'LYD',
                'MAD',
                'MDL',
                'MGA',
                'MKD',
                'MMK',
                'MNT',
                'MOP',
                'MRU',
                'MTL',
                'MUR',
                'MVR',
                'MWK',
                'MXN',
                'MYR',
                'MZN',
                'NAD',
                'NGN',
                'NIO',
                'NOK',
                'NPR',
                'NZD',
                'OMR',
                'PAB',
                'PEN',
                'PGK',
                'PHP',
                'PKR',
                'PLN',
                'PYG',
                'QAR',
                'RON',
                'RSD',
                'RUB',
                'RWF',
                'SAR',
                'SBD',
                'SCR',
                'SDG',
                'SEK',
                'SGD',
                'SRD',
                'SSP',
                'STN',
                'SYP',
                'SZL',
                'THB',
                'TJS',
                'TMT',
                'TND',
                'TOP',
                'TRY',
                'TTD',
                'TWD',
                'TZS',
                'UAH',
                'UGX',
                'USD',
                'UYU',
                'UZS',
                'VES',
                'VND',
                'VUV',
                'WST',
                'XAF',
                'XCD',
                'XOF',
                'XPF',
                'YER',
                'ZAR',
                'ZMW',
            ])
            .optional()
            .describe(
                '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
            ),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod
            .union([
                zod
                    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
                    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful'),
                zod.null(),
            ])
            .optional(),
        human_friendly_comparison_periods: zod.boolean().nullish(),
        feature_flag_confirmation_enabled: zod.boolean().nullish(),
        feature_flag_confirmation_message: zod.string().nullish(),
        default_evaluation_contexts_enabled: zod
            .boolean()
            .nullish()
            .describe('Whether to automatically apply default evaluation contexts to new feature flags'),
        require_evaluation_contexts: zod
            .boolean()
            .nullish()
            .describe('Whether to require at least one evaluation context tag when creating new feature flags'),
        default_data_theme: zod
            .number()
            .min(organizationsProjectsRotateSecretTokenPartialUpdateBodyDefaultDataThemeMin)
            .max(organizationsProjectsRotateSecretTokenPartialUpdateBodyDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Manage tracing product configuration for this project's canonical environment.
 * Mirrors the env-router action so /api/projects/:id/tracing_config/ resolves
 * alongside the legacy /api/environments/:id/tracing_config/ alias.
 */
export const organizationsProjectsTracingConfigPartialUpdateBodyTracingDistinctIdAttributeKeyMax = 200

export const OrganizationsProjectsTracingConfigPartialUpdateBody = /* @__PURE__ */ zod.object({
    tracing_distinct_id_attribute_key: zod
        .string()
        .max(organizationsProjectsTracingConfigPartialUpdateBodyTracingDistinctIdAttributeKeyMax)
        .optional()
        .describe(
            "Span attribute key whose value should match a person's distinct_id. Used by the person profile Traces tab. Defaults to 'posthogDistinctId' — the same convention logs use (see https:\/\/posthog.com\/docs\/logs\/link-session-replay). Traces arrive via plain OTel, so instrumentation must attach the key itself (e.g. via baggage and a BaggageSpanProcessor). Override only if your pipeline emits a different attribute."
        ),
})

/**
 * Create a new password for the sharing configuration.
 */
export const DashboardsSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

export const DashboardsSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemCreateBodyTypeMax = 100

export const desktopFileSystemCreateBodyRefMax = 100

export const DesktopFileSystemCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemUpdateBodyTypeMax = 100

export const desktopFileSystemUpdateBodyRefMax = 100

export const DesktopFileSystemUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemUpdateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemUpdateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemPartialUpdateBodyTypeMax = 100

export const desktopFileSystemPartialUpdateBodyRefMax = 100

export const DesktopFileSystemPartialUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string().optional(),
    type: zod.string().max(desktopFileSystemPartialUpdateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemPartialUpdateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Publish a new version of a freeform canvas's React source.
 *
 * Merges into the dashboard row's `meta` (never replaces it), so existing
 * keys like `channelId`/`templateId` survive. Appends a full-file version
 * snapshot and points `currentVersionId` at it — the server-side mirror of
 * the app's dashboardsService.saveFreeform.
 */
export const DesktopFileSystemCanvasPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        code: zod.string().optional(),
        prompt: zod.string().optional(),
        name: zod.string().optional(),
    })
    .describe("Payload for publishing a freeform canvas's React source via the agent.")

/**
 * Set or clear the Task associated with this folder's CONTEXT.md generation.
 */
export const DesktopFileSystemContextGenerationUpdateBody = /* @__PURE__ */ zod.object({
    task_id: zod
        .uuid()
        .nullable()
        .describe(
            "ID of the Task generating this folder's CONTEXT.md. Must reference a Task in the same team. Set to null to clear the association."
        ),
})

/**
 * Get count of all files in a folder.
 */
export const desktopFileSystemCountCreateBodyTypeMax = 100

export const desktopFileSystemCountCreateBodyRefMax = 100

export const DesktopFileSystemCountCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemCountCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemCountCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Publish a new version of the folder's instructions.
 */
export const desktopFileSystemInstructionsUpdateBodyBaseVersionMin = 0

export const DesktopFileSystemInstructionsUpdateBody = /* @__PURE__ */ zod.object({
    content: zod.string().describe('Full markdown instructions to publish as a new version for the folder.'),
    base_version: zod
        .number()
        .min(desktopFileSystemInstructionsUpdateBodyBaseVersionMin)
        .optional()
        .describe(
            "Latest version you are editing from, for optimistic concurrency. If provided and the folder's instructions have changed since, the request fails with 409. Use 0 when no instructions exist yet."
        ),
})

/**
 * Publish a new version of the folder's instructions.
 */
export const desktopFileSystemInstructionsPartialUpdateBodyBaseVersionMin = 0

export const DesktopFileSystemInstructionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    content: zod.string().optional().describe('Full markdown instructions to publish as a new version for the folder.'),
    base_version: zod
        .number()
        .min(desktopFileSystemInstructionsPartialUpdateBodyBaseVersionMin)
        .optional()
        .describe(
            "Latest version you are editing from, for optimistic concurrency. If provided and the folder's instructions have changed since, the request fails with 409. Use 0 when no instructions exist yet."
        ),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemLinkCreateBodyTypeMax = 100

export const desktopFileSystemLinkCreateBodyRefMax = 100

export const DesktopFileSystemLinkCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemLinkCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemLinkCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemMoveCreateBodyTypeMax = 100

export const desktopFileSystemMoveCreateBodyRefMax = 100

export const DesktopFileSystemMoveCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemMoveCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemMoveCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Get count of all files in a folder.
 */
export const desktopFileSystemCountByPathCreateBodyTypeMax = 100

export const desktopFileSystemCountByPathCreateBodyRefMax = 100

export const DesktopFileSystemCountByPathCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemCountByPathCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemCountByPathCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemLogViewCreateBodyTypeMax = 100

export const desktopFileSystemLogViewCreateBodyRefMax = 100

export const DesktopFileSystemLogViewCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemLogViewCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemLogViewCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * The file tree for the desktop product surface. Reuses all FileSystemViewSet behaviour but is
 * scoped to the "desktop" surface, so its tree is fully isolated from the default "web" tree.
 *
 * Adds per-folder, versioned markdown instructions describing the contents of a folder.
 */
export const desktopFileSystemUndoDeleteCreateBodyTypeMax = 100

export const desktopFileSystemUndoDeleteCreateBodyRefMax = 100

export const DesktopFileSystemUndoDeleteCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(desktopFileSystemUndoDeleteCreateBodyTypeMax).optional(),
    ref: zod.string().max(desktopFileSystemUndoDeleteCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const desktopFileSystemShortcutCreateBodyTypeMax = 100

export const desktopFileSystemShortcutCreateBodyRefMax = 100

export const desktopFileSystemShortcutCreateBodyOrderMin = -2147483648
export const desktopFileSystemShortcutCreateBodyOrderMax = 2147483647

export const DesktopFileSystemShortcutCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string().describe('Display path of the shortcut in the sidebar.'),
    type: zod
        .string()
        .max(desktopFileSystemShortcutCreateBodyTypeMax)
        .optional()
        .describe("Type of the linked item (e.g. 'folder', 'insight'), or blank."),
    ref: zod
        .string()
        .max(desktopFileSystemShortcutCreateBodyRefMax)
        .nullish()
        .describe('Reference to the linked item, scoped to its type. Null for href-only shortcuts.'),
    href: zod
        .string()
        .nullish()
        .describe('Destination URL the shortcut opens. Null when the shortcut points at an item by ref.'),
    order: zod
        .number()
        .min(desktopFileSystemShortcutCreateBodyOrderMin)
        .max(desktopFileSystemShortcutCreateBodyOrderMax)
        .optional()
        .describe("Display order within the user's shortcut list, ascending."),
})

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const desktopFileSystemShortcutUpdateBodyTypeMax = 100

export const desktopFileSystemShortcutUpdateBodyRefMax = 100

export const desktopFileSystemShortcutUpdateBodyOrderMin = -2147483648
export const desktopFileSystemShortcutUpdateBodyOrderMax = 2147483647

export const DesktopFileSystemShortcutUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string().describe('Display path of the shortcut in the sidebar.'),
    type: zod
        .string()
        .max(desktopFileSystemShortcutUpdateBodyTypeMax)
        .optional()
        .describe("Type of the linked item (e.g. 'folder', 'insight'), or blank."),
    ref: zod
        .string()
        .max(desktopFileSystemShortcutUpdateBodyRefMax)
        .nullish()
        .describe('Reference to the linked item, scoped to its type. Null for href-only shortcuts.'),
    href: zod
        .string()
        .nullish()
        .describe('Destination URL the shortcut opens. Null when the shortcut points at an item by ref.'),
    order: zod
        .number()
        .min(desktopFileSystemShortcutUpdateBodyOrderMin)
        .max(desktopFileSystemShortcutUpdateBodyOrderMax)
        .optional()
        .describe("Display order within the user's shortcut list, ascending."),
})

/**
 * Sidebar shortcuts for the desktop product surface. Reuses all FileSystemShortcutViewSet
 * behaviour but is scoped to the "desktop" surface, so its shortcuts are fully isolated from
 * the default "web" surface.
 */
export const desktopFileSystemShortcutPartialUpdateBodyTypeMax = 100

export const desktopFileSystemShortcutPartialUpdateBodyRefMax = 100

export const desktopFileSystemShortcutPartialUpdateBodyOrderMin = -2147483648
export const desktopFileSystemShortcutPartialUpdateBodyOrderMax = 2147483647

export const DesktopFileSystemShortcutPartialUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string().optional().describe('Display path of the shortcut in the sidebar.'),
    type: zod
        .string()
        .max(desktopFileSystemShortcutPartialUpdateBodyTypeMax)
        .optional()
        .describe("Type of the linked item (e.g. 'folder', 'insight'), or blank."),
    ref: zod
        .string()
        .max(desktopFileSystemShortcutPartialUpdateBodyRefMax)
        .nullish()
        .describe('Reference to the linked item, scoped to its type. Null for href-only shortcuts.'),
    href: zod
        .string()
        .nullish()
        .describe('Destination URL the shortcut opens. Null when the shortcut points at an item by ref.'),
    order: zod
        .number()
        .min(desktopFileSystemShortcutPartialUpdateBodyOrderMin)
        .max(desktopFileSystemShortcutPartialUpdateBodyOrderMax)
        .optional()
        .describe("Display order within the user's shortcut list, ascending."),
})

/**
 * Set the display order of the current user's shortcuts. `ordered_ids` becomes the new top-to-bottom order; any unknown IDs are rejected.
 */
export const DesktopFileSystemShortcutReorderCreateBody = /* @__PURE__ */ zod.object({
    ordered_ids: zod.array(zod.uuid()).describe("IDs of the current user's shortcuts in the desired display order."),
})

export const ExportsCreateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod.number().nullish(),
        insight: zod.number().nullish(),
        export_format: zod
            .enum([
                'image/png',
                'application/pdf',
                'text/csv',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'video/webm',
                'video/mp4',
                'image/gif',
                'application/json',
            ])
            .describe(
                '\* `image\/png` - image\/png\n\* `application\/pdf` - application\/pdf\n\* `text\/csv` - text\/csv\n\* `application\/vnd.openxmlformats-officedocument.spreadsheetml.sheet` - application\/vnd.openxmlformats-officedocument.spreadsheetml.sheet\n\* `video\/webm` - video\/webm\n\* `video\/mp4` - video\/mp4\n\* `image\/gif` - image\/gif\n\* `application\/json` - application\/json'
            ),
        export_context: zod.unknown().optional(),
    })
    .describe("Standard ExportedAsset serializer that doesn't return content.")

export const fileSystemCreateBodyTypeMax = 100

export const fileSystemCreateBodyRefMax = 100

export const FileSystemCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemUpdateBodyTypeMax = 100

export const fileSystemUpdateBodyRefMax = 100

export const FileSystemUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemUpdateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemUpdateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemPartialUpdateBodyTypeMax = 100

export const fileSystemPartialUpdateBodyRefMax = 100

export const FileSystemPartialUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string().optional(),
    type: zod.string().max(fileSystemPartialUpdateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemPartialUpdateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Get count of all files in a folder.
 */
export const fileSystemCountCreateBodyTypeMax = 100

export const fileSystemCountCreateBodyRefMax = 100

export const FileSystemCountCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemCountCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemCountCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemLinkCreateBodyTypeMax = 100

export const fileSystemLinkCreateBodyRefMax = 100

export const FileSystemLinkCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemLinkCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemLinkCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemMoveCreateBodyTypeMax = 100

export const fileSystemMoveCreateBodyRefMax = 100

export const FileSystemMoveCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemMoveCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemMoveCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Get count of all files in a folder.
 */
export const fileSystemCountByPathCreateBodyTypeMax = 100

export const fileSystemCountByPathCreateBodyRefMax = 100

export const FileSystemCountByPathCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemCountByPathCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemCountByPathCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemLogViewCreateBodyTypeMax = 100

export const fileSystemLogViewCreateBodyRefMax = 100

export const FileSystemLogViewCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemLogViewCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemLogViewCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemUndoDeleteCreateBodyTypeMax = 100

export const fileSystemUndoDeleteCreateBodyRefMax = 100

export const FileSystemUndoDeleteCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemUndoDeleteCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemUndoDeleteCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemShortcutCreateBodyTypeMax = 100

export const fileSystemShortcutCreateBodyRefMax = 100

export const fileSystemShortcutCreateBodyOrderMin = -2147483648
export const fileSystemShortcutCreateBodyOrderMax = 2147483647

export const FileSystemShortcutCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string().describe('Display path of the shortcut in the sidebar.'),
    type: zod
        .string()
        .max(fileSystemShortcutCreateBodyTypeMax)
        .optional()
        .describe("Type of the linked item (e.g. 'folder', 'insight'), or blank."),
    ref: zod
        .string()
        .max(fileSystemShortcutCreateBodyRefMax)
        .nullish()
        .describe('Reference to the linked item, scoped to its type. Null for href-only shortcuts.'),
    href: zod
        .string()
        .nullish()
        .describe('Destination URL the shortcut opens. Null when the shortcut points at an item by ref.'),
    order: zod
        .number()
        .min(fileSystemShortcutCreateBodyOrderMin)
        .max(fileSystemShortcutCreateBodyOrderMax)
        .optional()
        .describe("Display order within the user's shortcut list, ascending."),
})

export const fileSystemShortcutUpdateBodyTypeMax = 100

export const fileSystemShortcutUpdateBodyRefMax = 100

export const fileSystemShortcutUpdateBodyOrderMin = -2147483648
export const fileSystemShortcutUpdateBodyOrderMax = 2147483647

export const FileSystemShortcutUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string().describe('Display path of the shortcut in the sidebar.'),
    type: zod
        .string()
        .max(fileSystemShortcutUpdateBodyTypeMax)
        .optional()
        .describe("Type of the linked item (e.g. 'folder', 'insight'), or blank."),
    ref: zod
        .string()
        .max(fileSystemShortcutUpdateBodyRefMax)
        .nullish()
        .describe('Reference to the linked item, scoped to its type. Null for href-only shortcuts.'),
    href: zod
        .string()
        .nullish()
        .describe('Destination URL the shortcut opens. Null when the shortcut points at an item by ref.'),
    order: zod
        .number()
        .min(fileSystemShortcutUpdateBodyOrderMin)
        .max(fileSystemShortcutUpdateBodyOrderMax)
        .optional()
        .describe("Display order within the user's shortcut list, ascending."),
})

export const fileSystemShortcutPartialUpdateBodyTypeMax = 100

export const fileSystemShortcutPartialUpdateBodyRefMax = 100

export const fileSystemShortcutPartialUpdateBodyOrderMin = -2147483648
export const fileSystemShortcutPartialUpdateBodyOrderMax = 2147483647

export const FileSystemShortcutPartialUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string().optional().describe('Display path of the shortcut in the sidebar.'),
    type: zod
        .string()
        .max(fileSystemShortcutPartialUpdateBodyTypeMax)
        .optional()
        .describe("Type of the linked item (e.g. 'folder', 'insight'), or blank."),
    ref: zod
        .string()
        .max(fileSystemShortcutPartialUpdateBodyRefMax)
        .nullish()
        .describe('Reference to the linked item, scoped to its type. Null for href-only shortcuts.'),
    href: zod
        .string()
        .nullish()
        .describe('Destination URL the shortcut opens. Null when the shortcut points at an item by ref.'),
    order: zod
        .number()
        .min(fileSystemShortcutPartialUpdateBodyOrderMin)
        .max(fileSystemShortcutPartialUpdateBodyOrderMax)
        .optional()
        .describe("Display order within the user's shortcut list, ascending."),
})

/**
 * Set the display order of the current user's shortcuts. `ordered_ids` becomes the new top-to-bottom order; any unknown IDs are rejected.
 */
export const FileSystemShortcutReorderCreateBody = /* @__PURE__ */ zod.object({
    ordered_ids: zod.array(zod.uuid()).describe("IDs of the current user's shortcuts in the desired display order."),
})

/**
 * Create a new password for the sharing configuration.
 */
export const InsightsSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

export const InsightsSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

/**
 * Create a new password for the sharing configuration.
 */
export const NotebooksSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

export const NotebooksSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

export const ProductEnablementCreateBody = /* @__PURE__ */ zod.object({
    products: zod
        .array(
            zod
                .enum(['conversations', 'error_tracking', 'session_replay'])
                .describe(
                    '\* `conversations` - conversations\n\* `error_tracking` - error_tracking\n\* `session_replay` - session_replay'
                )
        )
        .min(1)
        .describe('Products to turn on for this project, each enabled with server-owned conservative defaults.'),
})

export const projectSecretApiKeysCreateBodyLabelMax = 40

export const ProjectSecretApiKeysCreateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysCreateBodyLabelMax),
    scopes: zod
        .array(zod.string())
        .describe(
            'Project-wide API scopes granted to this key. Project secret API keys do not honor object-level access controls, so a scope can access resources of that type even when per-resource RBAC would hide them from an individual user.'
        ),
})

export const projectSecretApiKeysUpdateBodyLabelMax = 40

export const ProjectSecretApiKeysUpdateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysUpdateBodyLabelMax),
    scopes: zod
        .array(zod.string())
        .describe(
            'Project-wide API scopes granted to this key. Project secret API keys do not honor object-level access controls, so a scope can access resources of that type even when per-resource RBAC would hide them from an individual user.'
        ),
})

export const projectSecretApiKeysPartialUpdateBodyLabelMax = 40

export const ProjectSecretApiKeysPartialUpdateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysPartialUpdateBodyLabelMax).optional(),
    scopes: zod
        .array(zod.string())
        .optional()
        .describe(
            'Project-wide API scopes granted to this key. Project secret API keys do not honor object-level access controls, so a scope can access resources of that type even when per-resource RBAC would hide them from an individual user.'
        ),
})

export const PropertyDefinitionsUpdateBody = /* @__PURE__ */ zod
    .object({
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        property_type: zod
            .union([
                zod
                    .enum(['DateTime', 'String', 'Numeric', 'Boolean', 'Duration'])
                    .describe(
                        '\* `DateTime` - DateTime\n\* `String` - String\n\* `Numeric` - Numeric\n\* `Boolean` - Boolean\n\* `Duration` - Duration'
                    ),
                zod.enum(['']),
                zod.null(),
            ])
            .optional(),
        verified: zod.boolean().optional(),
        hidden: zod.boolean().nullish(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const PropertyDefinitionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        property_type: zod
            .union([
                zod
                    .enum(['DateTime', 'String', 'Numeric', 'Boolean', 'Duration'])
                    .describe(
                        '\* `DateTime` - DateTime\n\* `String` - String\n\* `Numeric` - Numeric\n\* `Boolean` - Boolean\n\* `Duration` - Duration'
                    ),
                zod.enum(['']),
                zod.null(),
            ])
            .optional(),
        verified: zod.boolean().optional(),
        hidden: zod.boolean().nullish(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Bulk update tags on multiple objects.
 *
 * PAT access: this action has no ``required_scopes=`` on the decorator —
 * inheriting viewsets must add ``"bulk_update_tags"`` to their
 * ``scope_object_write_actions`` list to accept personal API keys.
 * Without that opt-in, ``APIScopePermission`` rejects PAT requests with
 * "This action does not support personal API key access". Done per-viewset
 * so granting ``<scope>:write`` for one resource doesn't leak access to
 * sibling resources that share this mixin.
 *
 * Accepts:
 * - {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}
 *
 * Actions:
 * - "add": Add tags to existing tags on each object
 * - "remove": Remove specific tags from each object
 * - "set": Replace all tags on each object with the provided list
 */
export const propertyDefinitionsBulkUpdateTagsCreateBodyIdsMax = 500

export const PropertyDefinitionsBulkUpdateTagsCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.number())
        .max(propertyDefinitionsBulkUpdateTagsCreateBodyIdsMax)
        .describe('List of object IDs to update tags on.'),
    action: zod
        .enum(['add', 'remove', 'set'])
        .describe('\* `add` - add\n\* `remove` - remove\n\* `set` - set')
        .describe(
            "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n\* `add` - add\n\* `remove` - remove\n\* `set` - set"
        ),
    tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
})

/**
 * Create a new password for the sharing configuration.
 */
export const SessionRecordingsSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

export const SessionRecordingsSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().optional(),
    password_required: zod.boolean().optional(),
})

/**
 * Replace the authenticated user's profile and settings. Pass `@me` as the UUID to update the authenticated user. Prefer the PATCH endpoint for partial updates — PUT requires every writable field to be provided.
 */
export const usersUpdateBodyFirstNameMax = 150

export const usersUpdateBodyLastNameMax = 150

export const usersUpdateBodyEmailMax = 254

export const usersUpdateBodyPasswordMax = 128

export const UsersUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersUpdateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersUpdateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

/**
 * Update one or more of the authenticated user's profile fields or settings.
 */
export const usersPartialUpdateBodyFirstNameMax = 150

export const usersPartialUpdateBodyLastNameMax = 150

export const usersPartialUpdateBodyEmailMax = 254

export const usersPartialUpdateBodyPasswordMax = 128

export const UsersPartialUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersPartialUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersPartialUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersPartialUpdateBodyEmailMax).optional(),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersPartialUpdateBodyPasswordMax).optional(),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

export const usersHedgehogConfigPartialUpdateBodyFirstNameMax = 150

export const usersHedgehogConfigPartialUpdateBodyLastNameMax = 150

export const usersHedgehogConfigPartialUpdateBodyEmailMax = 254

export const usersHedgehogConfigPartialUpdateBodyPasswordMax = 128

export const UsersHedgehogConfigPartialUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersHedgehogConfigPartialUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersHedgehogConfigPartialUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersHedgehogConfigPartialUpdateBodyEmailMax).optional(),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersHedgehogConfigPartialUpdateBodyPasswordMax).optional(),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

/**
 * Seed personal GitHub manage callback state before opening installation settings on GitHub.
 */
export const UsersIntegrationsGithubPrepareCallbackCreateBody = /* @__PURE__ */ zod.object({
    installation_id: zod.string().describe('GitHub App installation id being managed on github.com.'),
})

/**
 * Start GitHub linking: either full App install or OAuth-only (user-to-server).
 *
 * ``**_kwargs`` absorbs ``parent_lookup_uuid`` from the nested
 * ``/api/users/{uuid}/integrations/`` router (same pattern as ``local_evaluation``
 * under projects).
 *
 * Usually returns ``install_url`` pointing at ``/installations/new`` so the
 * user can pick any GitHub org (new or already connected).  GitHub's install
 * page handles both cases: orgs where the app is installed show "Configure"
 * (no admin needed), orgs where it isn't show "Install" (needs admin).
 *
 * **OAuth fast path:** when the current project already has a team-level
 * GitHub installation, and the user has no ``UserIntegration`` for that
 * installation yet, we skip the org picker and redirect straight to
 * ``/login/oauth/authorize`` so the user only authorizes themselves.
 * ``connect_from`` is preserved for first-party clients so they return to
 * the originating client immediately.
 *
 * In both cases the response key is ``install_url`` for compatibility with callers.
 * @summary Start GitHub personal integration linking
 */
export const UsersIntegrationsGithubStartCreateBody = /* @__PURE__ */ zod.object({
    team_id: zod
        .number()
        .nullish()
        .describe("Optional team\/project id (e.g. PostHog Code); web UI uses the session's current team."),
    connect_from: zod
        .string()
        .optional()
        .describe('Optional client hint (e.g. posthog_code) for return routing after OAuth.'),
})

/**
 * Mint a Sign-in-with-Slack invite URL initiated from settings, without
 * Slack-DM context. The returned URL takes the user through PostHog login
 * (already satisfied here), then to Slack OAuth, then back to our callback
 * which writes the ``UserIntegration`` row.
 *
 * Without body params, falls back to the user's ``current_team`` and that
 * team's first Slack ``Integration`` — works when there's exactly one
 * linkable workspace. With ``team_id`` + ``slack_team_id``, links against
 * the exact pair (what the frontend uses when a picker is shown).
 *
 * Refuses if the target team has no matching Slack workspace, if the
 * feature flag is off for the workspace, or if the user is already linked
 * to it.
 * @summary Start Slack identity link from settings
 */
export const UsersIntegrationsSlackStartCreateBody = /* @__PURE__ */ zod
    .object({
        team_id: zod
            .number()
            .nullish()
            .describe("Optional team\/project id to link against; defaults to the user's current team."),
        slack_team_id: zod
            .string()
            .nullish()
            .describe(
                'Specific Slack workspace id to link against, scoped to the team. Disambiguates when one team has multiple Slack integrations (rare).'
            ),
    })
    .describe(
        "Settings-initiated link can target a specific PostHog team + Slack workspace.\n\nBoth are optional — when omitted we fall back to the user's ``current_team``\nand that team's first Slack ``Integration`` (mirrors ``github_start`` for\nthe simple case). The frontend passes both explicitly once it has the\nlinkable-workspace list and the user has picked a workspace."
    )

/**
 * Mark the current user as having exited onboarding with a non-delegated reason.
 * Idempotent: the skip timestamp is only set on the first successful call.
 *
 * Callers wanting to delegate setup to a teammate must use the dedicated
 * /organizations/{id}/invites/delegate/ endpoint, which atomically creates the
 * invite and sets reason="delegated". This endpoint rejects that reason so state
 * can't be faked without a real invite.
 */
export const usersOnboardingSkipCreateBodyStepAtSkipMax = 64

export const UsersOnboardingSkipCreateBody = /* @__PURE__ */ zod
    .object({
        reason: zod
            .enum(['later', 'other'])
            .describe('\* `later` - Later\n\* `other` - Other')
            .describe(
                "Why the user is leaving onboarding. 'later' keeps them able to return; 'other' is a catch-all. 'delegated' is rejected here — use the delegate endpoint so the delegation invite is created atomically.\n\n\* `later` - Later\n\* `other` - Other"
            ),
        step_at_skip: zod
            .string()
            .max(usersOnboardingSkipCreateBodyStepAtSkipMax)
            .optional()
            .describe('Onboarding step key the user was on when skipping, for analytics only.'),
    })
    .describe(
        'Request body for POST \/api\/users\/{id}\/onboarding\/skip\/.\n\nSource of truth for OpenAPI \/ generated TS \/ zod \/ MCP — bind this serializer at\nruntime so the contract clients believe is enforced (length cap, choice validation,\nno extra fields) is actually enforced server-side.'
    )

/**
 * Idempotent upsert: if the (user, token) pair already exists, `platform` and `last_seen_at` are refreshed. Otherwise a new row is created.
 * @summary Register a push notification token
 */
export const usersPushTokensCreateBodyTokenMax = 512

export const UsersPushTokensCreateBody = /* @__PURE__ */ zod.object({
    token: zod
        .string()
        .max(usersPushTokensCreateBodyTokenMax)
        .describe("Opaque push token issued by the device's platform push service (e.g. an Expo push token)."),
    platform: zod
        .enum(['ios', 'android', 'web'])
        .describe('\* `ios` - iOS\n\* `android` - Android\n\* `web` - Web')
        .describe(
            'Device platform the token was issued for. One of `ios`, `android`, or `web`.\n\n\* `ios` - iOS\n\* `android` - Android\n\* `web` - Web'
        ),
})

/**
 * Delete the row matching `(user, token)`. Returns 204 even if no row matches so the mobile client can call this unconditionally when the user opts out.
 * @summary Unregister a push notification token
 */
export const usersPushTokensUnregisterCreateBodyTokenMax = 512

export const UsersPushTokensUnregisterCreateBody = /* @__PURE__ */ zod.object({
    token: zod
        .string()
        .max(usersPushTokensUnregisterCreateBodyTokenMax)
        .describe('The opaque push token to remove for the authenticated user.'),
})

export const usersScenePersonalisationCreateBodyFirstNameMax = 150

export const usersScenePersonalisationCreateBodyLastNameMax = 150

export const usersScenePersonalisationCreateBodyEmailMax = 254

export const usersScenePersonalisationCreateBodyPasswordMax = 128

export const UsersScenePersonalisationCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersScenePersonalisationCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersScenePersonalisationCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersScenePersonalisationCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersScenePersonalisationCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

/**
 * Generate new backup codes, invalidating any existing ones
 */
export const usersTwoFactorBackupCodesCreateBodyFirstNameMax = 150

export const usersTwoFactorBackupCodesCreateBodyLastNameMax = 150

export const usersTwoFactorBackupCodesCreateBodyEmailMax = 254

export const usersTwoFactorBackupCodesCreateBodyPasswordMax = 128

export const UsersTwoFactorBackupCodesCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersTwoFactorBackupCodesCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersTwoFactorBackupCodesCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersTwoFactorBackupCodesCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersTwoFactorBackupCodesCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

/**
 * Disable 2FA and remove all related devices
 */
export const usersTwoFactorDisableCreateBodyFirstNameMax = 150

export const usersTwoFactorDisableCreateBodyLastNameMax = 150

export const usersTwoFactorDisableCreateBodyEmailMax = 254

export const usersTwoFactorDisableCreateBodyPasswordMax = 128

export const UsersTwoFactorDisableCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersTwoFactorDisableCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersTwoFactorDisableCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersTwoFactorDisableCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersTwoFactorDisableCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

export const usersTwoFactorValidateCreateBodyFirstNameMax = 150

export const usersTwoFactorValidateCreateBodyLastNameMax = 150

export const usersTwoFactorValidateCreateBodyEmailMax = 254

export const usersTwoFactorValidateCreateBodyPasswordMax = 128

export const UsersTwoFactorValidateCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersTwoFactorValidateCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersTwoFactorValidateCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersTwoFactorValidateCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersTwoFactorValidateCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

export const usersValidate2faCreateBodyFirstNameMax = 150

export const usersValidate2faCreateBodyLastNameMax = 150

export const usersValidate2faCreateBodyEmailMax = 254

export const usersValidate2faCreateBodyPasswordMax = 128

export const UsersValidate2faCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersValidate2faCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersValidate2faCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersValidate2faCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersValidate2faCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

export const usersCancelEmailChangeRequestPartialUpdateBodyFirstNameMax = 150

export const usersCancelEmailChangeRequestPartialUpdateBodyLastNameMax = 150

export const usersCancelEmailChangeRequestPartialUpdateBodyEmailMax = 254

export const usersCancelEmailChangeRequestPartialUpdateBodyPasswordMax = 128

export const UsersCancelEmailChangeRequestPartialUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersCancelEmailChangeRequestPartialUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersCancelEmailChangeRequestPartialUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersCancelEmailChangeRequestPartialUpdateBodyEmailMax).optional(),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersCancelEmailChangeRequestPartialUpdateBodyPasswordMax).optional(),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

export const usersRequestEmailVerificationCreateBodyFirstNameMax = 150

export const usersRequestEmailVerificationCreateBodyLastNameMax = 150

export const usersRequestEmailVerificationCreateBodyEmailMax = 254

export const usersRequestEmailVerificationCreateBodyPasswordMax = 128

export const UsersRequestEmailVerificationCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersRequestEmailVerificationCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersRequestEmailVerificationCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersRequestEmailVerificationCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersRequestEmailVerificationCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})

export const usersVerifyEmailCreateBodyFirstNameMax = 150

export const usersVerifyEmailCreateBodyLastNameMax = 150

export const usersVerifyEmailCreateBodyEmailMax = 254

export const usersVerifyEmailCreateBodyPasswordMax = 128

export const UsersVerifyEmailCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersVerifyEmailCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersVerifyEmailCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersVerifyEmailCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project\/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('\* `disabled` - disabled\n\* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersVerifyEmailCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    theme_mode: zod
        .union([
            zod
                .enum(['light', 'dark', 'system'])
                .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
    hide_mcp_hints: zod
        .boolean()
        .optional()
        .describe(
            'When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.'
        ),
})
