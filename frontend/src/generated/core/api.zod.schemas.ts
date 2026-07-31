/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - core
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const cIMDVerificationTokenApiLabelMax = 40

export const CIMDVerificationTokenApi = zod.object({
    id: zod.uuid(),
    label: zod.string().max(cIMDVerificationTokenApiLabelMax),
    mask_value: zod.string().nullable(),
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }),
    last_used_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type CIMDVerificationTokenApi = zod.input<typeof CIMDVerificationTokenApi>
export type CIMDVerificationTokenApiOutput = zod.output<typeof CIMDVerificationTokenApi>

export const PaginatedCIMDVerificationTokenListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(CIMDVerificationTokenApi),
})

export type PaginatedCIMDVerificationTokenListApi = zod.input<typeof PaginatedCIMDVerificationTokenListApi>
export type PaginatedCIMDVerificationTokenListApiOutput = zod.output<typeof PaginatedCIMDVerificationTokenListApi>

export const cIMDVerificationTokenWithValueApiLabelMax = 40

export const CIMDVerificationTokenWithValueApi = zod
    .object({
        id: zod.uuid(),
        label: zod.string().max(cIMDVerificationTokenWithValueApiLabelMax),
        mask_value: zod.string().nullable(),
        created_by: UserBasicApi,
        created_at: zod.iso.datetime({ offset: true }),
        last_used_at: zod.iso.datetime({ offset: true }).nullable(),
        value: zod.string().describe('Plaintext token, only returned on creation'),
    })
    .describe(
        'Create-response variant that includes the plaintext token.\n\nOnly emitted from the create endpoint - storage-side we only persist the\nhash, so subsequent reads use the base serializer.'
    )

export type CIMDVerificationTokenWithValueApi = zod.input<typeof CIMDVerificationTokenWithValueApi>
export type CIMDVerificationTokenWithValueApiOutput = zod.output<typeof CIMDVerificationTokenWithValueApi>

export const organizationDomainApiDomainMax = 128

export const organizationDomainApiSsoEnforcementMax = 28

export const OrganizationDomainApi = zod.object({
    id: zod.uuid(),
    domain: zod.string().max(organizationDomainApiDomainMax),
    is_verified: zod.boolean().describe('Determines whether a domain is verified or not.'),
    verified_at: zod.iso.datetime({ offset: true }).nullable(),
    verification_challenge: zod.string(),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(organizationDomainApiSsoEnforcementMax).optional(),
    has_saml: zod
        .boolean()
        .describe(
            'Returns whether SAML is configured for the instance. Does not validate the user has the required license (that check is performed in other places).'
        ),
    has_scim: zod.boolean().describe('Returns whether SCIM is configured and enabled for this domain.'),
    scim_base_url: zod.string().nullable(),
    has_id_jag: zod.boolean().describe('Returns whether ID-JAG (XAA) is configured for this domain.'),
    identity_provider_config: zod
        .uuid()
        .nullish()
        .describe(
            'Linked IdP configuration (SAML\/SCIM\/XAA) that backs this domain. Must belong to the same organization.'
        ),
})

export type OrganizationDomainApi = zod.input<typeof OrganizationDomainApi>
export type OrganizationDomainApiOutput = zod.output<typeof OrganizationDomainApi>

export const PaginatedOrganizationDomainListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(OrganizationDomainApi),
})

export type PaginatedOrganizationDomainListApi = zod.input<typeof PaginatedOrganizationDomainListApi>
export type PaginatedOrganizationDomainListApiOutput = zod.output<typeof PaginatedOrganizationDomainListApi>

export const patchedOrganizationDomainApiDomainMax = 128

export const patchedOrganizationDomainApiSsoEnforcementMax = 28

export const PatchedOrganizationDomainApi = zod.object({
    id: zod.uuid().optional(),
    domain: zod.string().max(patchedOrganizationDomainApiDomainMax).optional(),
    is_verified: zod.boolean().optional().describe('Determines whether a domain is verified or not.'),
    verified_at: zod.iso.datetime({ offset: true }).nullish(),
    verification_challenge: zod.string().optional(),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(patchedOrganizationDomainApiSsoEnforcementMax).optional(),
    has_saml: zod
        .boolean()
        .optional()
        .describe(
            'Returns whether SAML is configured for the instance. Does not validate the user has the required license (that check is performed in other places).'
        ),
    has_scim: zod.boolean().optional().describe('Returns whether SCIM is configured and enabled for this domain.'),
    scim_base_url: zod.string().nullish(),
    has_id_jag: zod.boolean().optional().describe('Returns whether ID-JAG (XAA) is configured for this domain.'),
    identity_provider_config: zod
        .uuid()
        .nullish()
        .describe(
            'Linked IdP configuration (SAML\/SCIM\/XAA) that backs this domain. Must belong to the same organization.'
        ),
})

export type PatchedOrganizationDomainApi = zod.input<typeof PatchedOrganizationDomainApi>
export type PatchedOrganizationDomainApiOutput = zod.output<typeof PatchedOrganizationDomainApi>

export const identityProviderConfigApiNameMax = 255

export const identityProviderConfigApiSamlEntityIdMax = 512

export const identityProviderConfigApiSamlAcsUrlMax = 512

export const identityProviderConfigApiIdJagIssuerUrlMax = 512

export const identityProviderConfigApiIdJagJwksUrlMax = 512

export const identityProviderConfigApiIdJagAllowedClientsItemMax = 256

export const IdentityProviderConfigApi = zod.object({
    id: zod.uuid(),
    name: zod
        .string()
        .max(identityProviderConfigApiNameMax)
        .optional()
        .describe("Display name for this IdP configuration (e.g. 'Okta production')."),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    has_saml: zod.boolean().describe('Whether SAML is fully configured on this config.'),
    saml_entity_id: zod
        .string()
        .max(identityProviderConfigApiSamlEntityIdMax)
        .nullish()
        .describe('SAML IdP entity ID (issuer).'),
    saml_acs_url: zod
        .string()
        .max(identityProviderConfigApiSamlAcsUrlMax)
        .nullish()
        .describe('SAML single sign-on (ACS) URL the IdP redirects to.'),
    saml_x509_cert: zod.string().nullish().describe('SAML IdP X.509 signing certificate (PEM).'),
    has_scim: zod.boolean().describe('Whether SCIM is enabled and a bearer token is set on this config.'),
    scim_enabled: zod
        .boolean()
        .optional()
        .describe(
            'Whether SCIM provisioning is enabled. Setting this true generates a bearer token (returned once); setting it false clears the token.'
        ),
    scim_bearer_token: zod
        .string()
        .nullable()
        .describe(
            'Plaintext SCIM bearer token. Only returned once, immediately after SCIM is enabled or the token is regenerated; null otherwise.'
        ),
    has_id_jag: zod.boolean().describe('Whether ID-JAG (XAA) is configured on this config.'),
    id_jag_issuer_url: zod
        .string()
        .max(identityProviderConfigApiIdJagIssuerUrlMax)
        .nullish()
        .describe('Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG.'),
    id_jag_jwks_url: zod
        .string()
        .max(identityProviderConfigApiIdJagJwksUrlMax)
        .nullish()
        .describe('Override JWKS URL. Defaults to OIDC discovery on the issuer URL.'),
    id_jag_allowed_clients: zod
        .array(zod.string().max(identityProviderConfigApiIdJagAllowedClientsItemMax))
        .optional()
        .describe('Allowed ID-JAG client IDs. Empty list allows any client_id.'),
})

export type IdentityProviderConfigApi = zod.input<typeof IdentityProviderConfigApi>
export type IdentityProviderConfigApiOutput = zod.output<typeof IdentityProviderConfigApi>

export const PaginatedIdentityProviderConfigListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(IdentityProviderConfigApi),
})

export type PaginatedIdentityProviderConfigListApi = zod.input<typeof PaginatedIdentityProviderConfigListApi>
export type PaginatedIdentityProviderConfigListApiOutput = zod.output<typeof PaginatedIdentityProviderConfigListApi>

export const patchedIdentityProviderConfigApiNameMax = 255

export const patchedIdentityProviderConfigApiSamlEntityIdMax = 512

export const patchedIdentityProviderConfigApiSamlAcsUrlMax = 512

export const patchedIdentityProviderConfigApiIdJagIssuerUrlMax = 512

export const patchedIdentityProviderConfigApiIdJagJwksUrlMax = 512

export const patchedIdentityProviderConfigApiIdJagAllowedClientsItemMax = 256

export const PatchedIdentityProviderConfigApi = zod.object({
    id: zod.uuid().optional(),
    name: zod
        .string()
        .max(patchedIdentityProviderConfigApiNameMax)
        .optional()
        .describe("Display name for this IdP configuration (e.g. 'Okta production')."),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
    has_saml: zod.boolean().optional().describe('Whether SAML is fully configured on this config.'),
    saml_entity_id: zod
        .string()
        .max(patchedIdentityProviderConfigApiSamlEntityIdMax)
        .nullish()
        .describe('SAML IdP entity ID (issuer).'),
    saml_acs_url: zod
        .string()
        .max(patchedIdentityProviderConfigApiSamlAcsUrlMax)
        .nullish()
        .describe('SAML single sign-on (ACS) URL the IdP redirects to.'),
    saml_x509_cert: zod.string().nullish().describe('SAML IdP X.509 signing certificate (PEM).'),
    has_scim: zod.boolean().optional().describe('Whether SCIM is enabled and a bearer token is set on this config.'),
    scim_enabled: zod
        .boolean()
        .optional()
        .describe(
            'Whether SCIM provisioning is enabled. Setting this true generates a bearer token (returned once); setting it false clears the token.'
        ),
    scim_bearer_token: zod
        .string()
        .nullish()
        .describe(
            'Plaintext SCIM bearer token. Only returned once, immediately after SCIM is enabled or the token is regenerated; null otherwise.'
        ),
    has_id_jag: zod.boolean().optional().describe('Whether ID-JAG (XAA) is configured on this config.'),
    id_jag_issuer_url: zod
        .string()
        .max(patchedIdentityProviderConfigApiIdJagIssuerUrlMax)
        .nullish()
        .describe('Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG.'),
    id_jag_jwks_url: zod
        .string()
        .max(patchedIdentityProviderConfigApiIdJagJwksUrlMax)
        .nullish()
        .describe('Override JWKS URL. Defaults to OIDC discovery on the issuer URL.'),
    id_jag_allowed_clients: zod
        .array(zod.string().max(patchedIdentityProviderConfigApiIdJagAllowedClientsItemMax))
        .optional()
        .describe('Allowed ID-JAG client IDs. Empty list allows any client_id.'),
})

export type PatchedIdentityProviderConfigApi = zod.input<typeof PatchedIdentityProviderConfigApi>
export type PatchedIdentityProviderConfigApiOutput = zod.output<typeof PatchedIdentityProviderConfigApi>

export const SCIMTokenResponseApi = zod.object({
    scim_enabled: zod.boolean().describe('Whether SCIM is enabled for this config.'),
    scim_bearer_token: zod.string().describe('Newly generated plaintext SCIM bearer token. Only returned once.'),
})

export type SCIMTokenResponseApi = zod.input<typeof SCIMTokenResponseApi>
export type SCIMTokenResponseApiOutput = zod.output<typeof SCIMTokenResponseApi>

export const OrganizationMembershipLevelEnumApi = zod
    .union([zod.literal(1), zod.literal(8), zod.literal(15)])
    .describe('\* `1` - member\n\* `8` - administrator\n\* `15` - owner')

export type OrganizationMembershipLevelEnumApi = zod.input<typeof OrganizationMembershipLevelEnumApi>
export type OrganizationMembershipLevelEnumApiOutput = zod.output<typeof OrganizationMembershipLevelEnumApi>

export const organizationInviteApiTargetEmailMax = 254

export const organizationInviteApiFirstNameMax = 30

export const organizationInviteApiSendEmailDefault = true
export const organizationInviteApiCombinePendingInvitesDefault = false

export const OrganizationInviteApi = zod.object({
    id: zod.uuid(),
    target_email: zod.email().max(organizationInviteApiTargetEmailMax),
    first_name: zod.string().max(organizationInviteApiFirstNameMax).optional(),
    emailing_attempt_made: zod.boolean(),
    level: OrganizationMembershipLevelEnumApi.optional(),
    is_expired: zod.boolean().describe('Check if invite is older than INVITE_DAYS_VALIDITY days.'),
    created_by: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    message: zod.string().nullish(),
    private_project_access: zod
        .unknown()
        .optional()
        .describe('List of team IDs and corresponding access levels to private projects.'),
    send_email: zod.boolean().default(organizationInviteApiSendEmailDefault),
    combine_pending_invites: zod.boolean().default(organizationInviteApiCombinePendingInvitesDefault),
})

export type OrganizationInviteApi = zod.input<typeof OrganizationInviteApi>
export type OrganizationInviteApiOutput = zod.output<typeof OrganizationInviteApi>

export const PaginatedOrganizationInviteListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(OrganizationInviteApi),
})

export type PaginatedOrganizationInviteListApi = zod.input<typeof PaginatedOrganizationInviteListApi>
export type PaginatedOrganizationInviteListApiOutput = zod.output<typeof PaginatedOrganizationInviteListApi>

export const organizationInviteDelegateApiMessageMax = 1000

export const organizationInviteDelegateApiStepAtDelegationMax = 64

export const OrganizationInviteDelegateApi = zod.object({
    target_email: zod
        .email()
        .describe(
            "Email of the teammate who should complete setup on the inviter's behalf. Receives a PostHog-branded delegation invite granting admin-level membership on accept."
        ),
    message: zod
        .string()
        .max(organizationInviteDelegateApiMessageMax)
        .optional()
        .describe('Optional personal message included in the delegation email (up to 1000 characters).'),
    step_at_delegation: zod
        .string()
        .max(organizationInviteDelegateApiStepAtDelegationMax)
        .optional()
        .describe('Onboarding step key the delegator was on when delegating, for analytics only.'),
})

export type OrganizationInviteDelegateApi = zod.input<typeof OrganizationInviteDelegateApi>
export type OrganizationInviteDelegateApiOutput = zod.output<typeof OrganizationInviteDelegateApi>

export const organizationOAuthApplicationApiNameMax = 255

export const organizationOAuthApplicationApiClientIdMax = 100

export const OrganizationOAuthApplicationApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(organizationOAuthApplicationApiNameMax).optional(),
        client_id: zod.string().max(organizationOAuthApplicationApiClientIdMax).optional(),
        redirect_uris_list: zod.array(zod.string()),
        is_verified: zod.boolean().optional().describe('True if this application has been verified by PostHog'),
        created: zod.iso.datetime({ offset: true }),
        updated: zod.iso.datetime({ offset: true }),
    })
    .describe('Serializer for organization-scoped OAuth applications (read-only).')

export type OrganizationOAuthApplicationApi = zod.input<typeof OrganizationOAuthApplicationApi>
export type OrganizationOAuthApplicationApiOutput = zod.output<typeof OrganizationOAuthApplicationApi>

export const PaginatedOrganizationOAuthApplicationListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(OrganizationOAuthApplicationApi),
})

export type PaginatedOrganizationOAuthApplicationListApi = zod.input<
    typeof PaginatedOrganizationOAuthApplicationListApi
>
export type PaginatedOrganizationOAuthApplicationListApiOutput = zod.output<
    typeof PaginatedOrganizationOAuthApplicationListApi
>

export const ProjectBackwardCompatBasicApi = zod
    .object({
        id: zod.number(),
        uuid: zod.uuid(),
        organization: zod.uuid(),
        project_id: zod.number().describe('ID of the project this environment belongs to.'),
        api_token: zod.string(),
        name: zod.string(),
        completed_snippet_onboarding: zod.boolean(),
        has_completed_onboarding_for: zod.unknown(),
        ingested_event: zod.boolean(),
        is_demo: zod.boolean(),
        timezone: zod.string(),
        access_control: zod.boolean(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

export type ProjectBackwardCompatBasicApi = zod.input<typeof ProjectBackwardCompatBasicApi>
export type ProjectBackwardCompatBasicApiOutput = zod.output<typeof ProjectBackwardCompatBasicApi>

export const PaginatedProjectBackwardCompatBasicListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ProjectBackwardCompatBasicApi),
})

export type PaginatedProjectBackwardCompatBasicListApi = zod.input<typeof PaginatedProjectBackwardCompatBasicListApi>
export type PaginatedProjectBackwardCompatBasicListApiOutput = zod.output<
    typeof PaginatedProjectBackwardCompatBasicListApi
>

export const EffectiveMembershipLevelEnumApi = zod.union([zod.literal(1), zod.literal(8), zod.literal(15)])

export type EffectiveMembershipLevelEnumApi = zod.input<typeof EffectiveMembershipLevelEnumApi>
export type EffectiveMembershipLevelEnumApiOutput = zod.output<typeof EffectiveMembershipLevelEnumApi>

export const SessionRecordingRetentionPeriodEnumApi = zod
    .enum(['30d', '90d', '1y', '5y'])
    .describe('\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years')

export type SessionRecordingRetentionPeriodEnumApi = zod.input<typeof SessionRecordingRetentionPeriodEnumApi>
export type SessionRecordingRetentionPeriodEnumApiOutput = zod.output<typeof SessionRecordingRetentionPeriodEnumApi>

export const WeekStartDayEnumApi = zod
    .union([zod.literal(0), zod.literal(1)])
    .describe('\* `0` - Sunday\n\* `1` - Monday')

export type WeekStartDayEnumApi = zod.input<typeof WeekStartDayEnumApi>
export type WeekStartDayEnumApiOutput = zod.output<typeof WeekStartDayEnumApi>

export const BusinessModelEnumApi = zod
    .enum(['b2b', 'b2c', 'other'])
    .describe('\* `b2b` - B2B\n\* `b2c` - B2C\n\* `other` - Other')

export type BusinessModelEnumApi = zod.input<typeof BusinessModelEnumApi>
export type BusinessModelEnumApiOutput = zod.output<typeof BusinessModelEnumApi>

export const AvailableSetupTaskIdsEnumApi = zod
    .enum([
        'ingest_first_event',
        'set_up_reverse_proxy',
        'create_first_insight',
        'create_first_dashboard',
        'track_custom_events',
        'define_actions',
        'set_up_cohorts',
        'explore_trends_insight',
        'create_funnel',
        'explore_retention_insight',
        'explore_paths_insight',
        'explore_stickiness_insight',
        'explore_lifecycle_insight',
        'add_authorized_domain',
        'set_up_web_vitals',
        'review_web_analytics_dashboard',
        'filter_web_analytics',
        'set_up_web_analytics_conversion_goals',
        'visit_web_vitals_dashboard',
        'setup_session_recordings',
        'watch_session_recording',
        'configure_recording_settings',
        'create_recording_playlist',
        'enable_console_logs',
        'create_feature_flag',
        'implement_flag_in_code',
        'update_feature_flag_release_conditions',
        'create_multivariate_flag',
        'set_up_flag_payloads',
        'set_up_flag_evaluation_runtimes',
        'create_experiment',
        'implement_experiment_variants',
        'launch_experiment',
        'review_experiment_results',
        'create_survey',
        'launch_survey',
        'collect_survey_responses',
        'connect_source',
        'run_first_query',
        'join_external_data',
        'create_saved_view',
        'enable_error_tracking',
        'upload_source_maps',
        'view_first_error',
        'resolve_first_error',
        'ingest_first_llm_event',
        'view_first_trace',
        'track_costs',
        'set_up_llm_evaluation',
        'run_ai_playground',
        'enable_log_capture',
        'view_first_logs',
        'create_first_workflow',
        'set_up_first_workflow_channel',
        'configure_workflow_trigger',
        'add_workflow_action',
        'launch_workflow',
        'create_first_endpoint',
        'configure_endpoint',
        'test_endpoint',
        'create_early_access_feature',
        'update_feature_stage',
        'use_posthog_ai',
        'use_posthog_code',
        'use_posthog_mcp',
        'use_posthog_in_slack',
    ])
    .describe(
        '\* `ingest_first_event` - ingest_first_event\n\* `set_up_reverse_proxy` - set_up_reverse_proxy\n\* `create_first_insight` - create_first_insight\n\* `create_first_dashboard` - create_first_dashboard\n\* `track_custom_events` - track_custom_events\n\* `define_actions` - define_actions\n\* `set_up_cohorts` - set_up_cohorts\n\* `explore_trends_insight` - explore_trends_insight\n\* `create_funnel` - create_funnel\n\* `explore_retention_insight` - explore_retention_insight\n\* `explore_paths_insight` - explore_paths_insight\n\* `explore_stickiness_insight` - explore_stickiness_insight\n\* `explore_lifecycle_insight` - explore_lifecycle_insight\n\* `add_authorized_domain` - add_authorized_domain\n\* `set_up_web_vitals` - set_up_web_vitals\n\* `review_web_analytics_dashboard` - review_web_analytics_dashboard\n\* `filter_web_analytics` - filter_web_analytics\n\* `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals\n\* `visit_web_vitals_dashboard` - visit_web_vitals_dashboard\n\* `setup_session_recordings` - setup_session_recordings\n\* `watch_session_recording` - watch_session_recording\n\* `configure_recording_settings` - configure_recording_settings\n\* `create_recording_playlist` - create_recording_playlist\n\* `enable_console_logs` - enable_console_logs\n\* `create_feature_flag` - create_feature_flag\n\* `implement_flag_in_code` - implement_flag_in_code\n\* `update_feature_flag_release_conditions` - update_feature_flag_release_conditions\n\* `create_multivariate_flag` - create_multivariate_flag\n\* `set_up_flag_payloads` - set_up_flag_payloads\n\* `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes\n\* `create_experiment` - create_experiment\n\* `implement_experiment_variants` - implement_experiment_variants\n\* `launch_experiment` - launch_experiment\n\* `review_experiment_results` - review_experiment_results\n\* `create_survey` - create_survey\n\* `launch_survey` - launch_survey\n\* `collect_survey_responses` - collect_survey_responses\n\* `connect_source` - connect_source\n\* `run_first_query` - run_first_query\n\* `join_external_data` - join_external_data\n\* `create_saved_view` - create_saved_view\n\* `enable_error_tracking` - enable_error_tracking\n\* `upload_source_maps` - upload_source_maps\n\* `view_first_error` - view_first_error\n\* `resolve_first_error` - resolve_first_error\n\* `ingest_first_llm_event` - ingest_first_llm_event\n\* `view_first_trace` - view_first_trace\n\* `track_costs` - track_costs\n\* `set_up_llm_evaluation` - set_up_llm_evaluation\n\* `run_ai_playground` - run_ai_playground\n\* `enable_log_capture` - enable_log_capture\n\* `view_first_logs` - view_first_logs\n\* `create_first_workflow` - create_first_workflow\n\* `set_up_first_workflow_channel` - set_up_first_workflow_channel\n\* `configure_workflow_trigger` - configure_workflow_trigger\n\* `add_workflow_action` - add_workflow_action\n\* `launch_workflow` - launch_workflow\n\* `create_first_endpoint` - create_first_endpoint\n\* `configure_endpoint` - configure_endpoint\n\* `test_endpoint` - test_endpoint\n\* `create_early_access_feature` - create_early_access_feature\n\* `update_feature_stage` - update_feature_stage\n\* `use_posthog_ai` - use_posthog_ai\n\* `use_posthog_code` - use_posthog_code\n\* `use_posthog_mcp` - use_posthog_mcp\n\* `use_posthog_in_slack` - use_posthog_in_slack'
    )

export type AvailableSetupTaskIdsEnumApi = zod.input<typeof AvailableSetupTaskIdsEnumApi>
export type AvailableSetupTaskIdsEnumApiOutput = zod.output<typeof AvailableSetupTaskIdsEnumApi>

export const BaseCurrencyEnumApi = zod
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
    .describe(
        '\* `AED` - AED\n\* `AFN` - AFN\n\* `ALL` - ALL\n\* `AMD` - AMD\n\* `ANG` - ANG\n\* `AOA` - AOA\n\* `ARS` - ARS\n\* `AUD` - AUD\n\* `AWG` - AWG\n\* `AZN` - AZN\n\* `BAM` - BAM\n\* `BBD` - BBD\n\* `BDT` - BDT\n\* `BGN` - BGN\n\* `BHD` - BHD\n\* `BIF` - BIF\n\* `BMD` - BMD\n\* `BND` - BND\n\* `BOB` - BOB\n\* `BRL` - BRL\n\* `BSD` - BSD\n\* `BTC` - BTC\n\* `BTN` - BTN\n\* `BWP` - BWP\n\* `BYN` - BYN\n\* `BZD` - BZD\n\* `CAD` - CAD\n\* `CDF` - CDF\n\* `CHF` - CHF\n\* `CLP` - CLP\n\* `CNY` - CNY\n\* `COP` - COP\n\* `CRC` - CRC\n\* `CVE` - CVE\n\* `CZK` - CZK\n\* `DJF` - DJF\n\* `DKK` - DKK\n\* `DOP` - DOP\n\* `DZD` - DZD\n\* `EGP` - EGP\n\* `ERN` - ERN\n\* `ETB` - ETB\n\* `EUR` - EUR\n\* `FJD` - FJD\n\* `GBP` - GBP\n\* `GEL` - GEL\n\* `GHS` - GHS\n\* `GIP` - GIP\n\* `GMD` - GMD\n\* `GNF` - GNF\n\* `GTQ` - GTQ\n\* `GYD` - GYD\n\* `HKD` - HKD\n\* `HNL` - HNL\n\* `HRK` - HRK\n\* `HTG` - HTG\n\* `HUF` - HUF\n\* `IDR` - IDR\n\* `ILS` - ILS\n\* `INR` - INR\n\* `IQD` - IQD\n\* `IRR` - IRR\n\* `ISK` - ISK\n\* `JMD` - JMD\n\* `JOD` - JOD\n\* `JPY` - JPY\n\* `KES` - KES\n\* `KGS` - KGS\n\* `KHR` - KHR\n\* `KMF` - KMF\n\* `KRW` - KRW\n\* `KWD` - KWD\n\* `KYD` - KYD\n\* `KZT` - KZT\n\* `LAK` - LAK\n\* `LBP` - LBP\n\* `LKR` - LKR\n\* `LRD` - LRD\n\* `LTL` - LTL\n\* `LVL` - LVL\n\* `LSL` - LSL\n\* `LYD` - LYD\n\* `MAD` - MAD\n\* `MDL` - MDL\n\* `MGA` - MGA\n\* `MKD` - MKD\n\* `MMK` - MMK\n\* `MNT` - MNT\n\* `MOP` - MOP\n\* `MRU` - MRU\n\* `MTL` - MTL\n\* `MUR` - MUR\n\* `MVR` - MVR\n\* `MWK` - MWK\n\* `MXN` - MXN\n\* `MYR` - MYR\n\* `MZN` - MZN\n\* `NAD` - NAD\n\* `NGN` - NGN\n\* `NIO` - NIO\n\* `NOK` - NOK\n\* `NPR` - NPR\n\* `NZD` - NZD\n\* `OMR` - OMR\n\* `PAB` - PAB\n\* `PEN` - PEN\n\* `PGK` - PGK\n\* `PHP` - PHP\n\* `PKR` - PKR\n\* `PLN` - PLN\n\* `PYG` - PYG\n\* `QAR` - QAR\n\* `RON` - RON\n\* `RSD` - RSD\n\* `RUB` - RUB\n\* `RWF` - RWF\n\* `SAR` - SAR\n\* `SBD` - SBD\n\* `SCR` - SCR\n\* `SDG` - SDG\n\* `SEK` - SEK\n\* `SGD` - SGD\n\* `SRD` - SRD\n\* `SSP` - SSP\n\* `STN` - STN\n\* `SYP` - SYP\n\* `SZL` - SZL\n\* `THB` - THB\n\* `TJS` - TJS\n\* `TMT` - TMT\n\* `TND` - TND\n\* `TOP` - TOP\n\* `TRY` - TRY\n\* `TTD` - TTD\n\* `TWD` - TWD\n\* `TZS` - TZS\n\* `UAH` - UAH\n\* `UGX` - UGX\n\* `USD` - USD\n\* `UYU` - UYU\n\* `UZS` - UZS\n\* `VES` - VES\n\* `VND` - VND\n\* `VUV` - VUV\n\* `WST` - WST\n\* `XAF` - XAF\n\* `XCD` - XCD\n\* `XOF` - XOF\n\* `XPF` - XPF\n\* `YER` - YER\n\* `ZAR` - ZAR\n\* `ZMW` - ZMW'
    )

export type BaseCurrencyEnumApi = zod.input<typeof BaseCurrencyEnumApi>
export type BaseCurrencyEnumApiOutput = zod.output<typeof BaseCurrencyEnumApi>

export const TeamRevenueAnalyticsConfigApi = zod.object({
    base_currency: BaseCurrencyEnumApi.optional(),
    events: zod.unknown().optional(),
    filter_test_accounts: zod.boolean().optional(),
})

export type TeamRevenueAnalyticsConfigApi = zod.input<typeof TeamRevenueAnalyticsConfigApi>
export type TeamRevenueAnalyticsConfigApiOutput = zod.output<typeof TeamRevenueAnalyticsConfigApi>

export const AttributionModeEnumApi = zod
    .enum(['first_touch', 'last_touch', 'linear', 'time_decay', 'position_based'])
    .describe(
        '\* `first_touch` - First Touch\n\* `last_touch` - Last Touch\n\* `linear` - Linear\n\* `time_decay` - Time Decay\n\* `position_based` - Position Based'
    )

export type AttributionModeEnumApi = zod.input<typeof AttributionModeEnumApi>
export type AttributionModeEnumApiOutput = zod.output<typeof AttributionModeEnumApi>

export const teamMarketingAnalyticsConfigApiAttributionWindowDaysMax = 90

export const TeamMarketingAnalyticsConfigApi = zod.object({
    sources_map: zod.unknown().optional(),
    conversion_goals: zod.unknown().optional(),
    attribution_window_days: zod
        .number()
        .min(1)
        .max(teamMarketingAnalyticsConfigApiAttributionWindowDaysMax)
        .optional(),
    attribution_mode: AttributionModeEnumApi.optional(),
    campaign_name_mappings: zod.unknown().optional(),
    custom_source_mappings: zod.unknown().optional(),
    campaign_field_preferences: zod.unknown().optional(),
})

export type TeamMarketingAnalyticsConfigApi = zod.input<typeof TeamMarketingAnalyticsConfigApi>
export type TeamMarketingAnalyticsConfigApiOutput = zod.output<typeof TeamMarketingAnalyticsConfigApi>

export const TeamCustomerAnalyticsConfigApi = zod.object({
    activity_event: zod.unknown().optional().describe('Event used as the activity signal (DAU\/WAU\/MAU).'),
    signup_pageview_event: zod.unknown().optional().describe('Event used to count signup pageviews on dashboards.'),
    signup_event: zod.unknown().optional().describe('Event used to count signups on dashboards.'),
    subscription_event: zod.unknown().optional().describe('Event used to count subscriptions on dashboards.'),
    payment_event: zod.unknown().optional().describe('Event used to count payments on dashboards.'),
    account_group_type_index: zod
        .number()
        .nullish()
        .describe(
            'Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.'
        ),
})

export type TeamCustomerAnalyticsConfigApi = zod.input<typeof TeamCustomerAnalyticsConfigApi>
export type TeamCustomerAnalyticsConfigApiOutput = zod.output<typeof TeamCustomerAnalyticsConfigApi>

export const EmailTrackingConsentModeEnumApi = zod
    .enum(['off', 'opt_out', 'opt_in'])
    .describe('\* `off` - Off\n\* `opt_out` - Opt Out\n\* `opt_in` - Opt In')

export type EmailTrackingConsentModeEnumApi = zod.input<typeof EmailTrackingConsentModeEnumApi>
export type EmailTrackingConsentModeEnumApiOutput = zod.output<typeof EmailTrackingConsentModeEnumApi>

export const TeamWorkflowsConfigApi = zod.object({
    capture_workflows_engagement_events: zod
        .boolean()
        .optional()
        .describe(
            'When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_\*) alongside the existing workflow metrics.'
        ),
    email_tracking_consent_mode: EmailTrackingConsentModeEnumApi.optional().describe(
        "Recipient-consent enforcement for open\/click tracking on marketing workflow emails. 'off': no enforcement, tracking follows each email step's own setting. 'opt_out': track by default but not recipients who have opted out. 'opt_in': only track recipients who have explicitly opted in. Transactional emails are exempt from consent enforcement.\n\n\* `off` - Off\n\* `opt_out` - Opt Out\n\* `opt_in` - Opt In"
    ),
})

export type TeamWorkflowsConfigApi = zod.input<typeof TeamWorkflowsConfigApi>
export type TeamWorkflowsConfigApiOutput = zod.output<typeof TeamWorkflowsConfigApi>

export const CookielessServerHashModeEnumApi = zod
    .union([zod.literal(0), zod.literal(1), zod.literal(2)])
    .describe('\* `0` - Disabled\n\* `1` - Stateless\n\* `2` - Stateful')

export type CookielessServerHashModeEnumApi = zod.input<typeof CookielessServerHashModeEnumApi>
export type CookielessServerHashModeEnumApiOutput = zod.output<typeof CookielessServerHashModeEnumApi>

export const projectBackwardCompatApiNameMax = 200

export const projectBackwardCompatApiProductDescriptionMax = 1000

export const projectBackwardCompatApiAppUrlsItemMax = 200

export const projectBackwardCompatApiPersonDisplayNamePropertiesItemMax = 400

export const projectBackwardCompatApiSessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const projectBackwardCompatApiSessionRecordingMinimumDurationMillisecondsMin = 0
export const projectBackwardCompatApiSessionRecordingMinimumDurationMillisecondsMax = 30000

export const projectBackwardCompatApiSessionRecordingTriggerMatchTypeConfigMax = 24

export const projectBackwardCompatApiRecordingDomainsItemMax = 200

export const projectBackwardCompatApiDefaultDataThemeMin = -2147483648
export const projectBackwardCompatApiDefaultDataThemeMax = 2147483647

export const ProjectBackwardCompatApi = zod
    .object({
        id: zod.number(),
        organization: zod.uuid(),
        name: zod
            .string()
            .min(1)
            .max(projectBackwardCompatApiNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(projectBackwardCompatApiProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        created_at: zod.iso.datetime({ offset: true }),
        effective_membership_level: EffectiveMembershipLevelEnumApi,
        has_group_types: zod.boolean(),
        group_types: zod.array(zod.record(zod.string(), zod.unknown())),
        live_events_token: zod.string().nullable(),
        updated_at: zod.iso.datetime({ offset: true }).nullable(),
        uuid: zod.uuid(),
        api_token: zod.string(),
        app_urls: zod.array(zod.string().max(projectBackwardCompatApiAppUrlsItemMax).nullable()).optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        ingested_event: zod.boolean(),
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
            .array(zod.string().max(projectBackwardCompatApiPersonDisplayNamePropertiesItemMax))
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
            .stringFormat('decimal', projectBackwardCompatApiSessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(projectBackwardCompatApiSessionRecordingMinimumDurationMillisecondsMin)
            .max(projectBackwardCompatApiSessionRecordingMinimumDurationMillisecondsMax)
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
            .max(projectBackwardCompatApiSessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: SessionRecordingRetentionPeriodEnumApi.optional().describe(
            'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
        ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([WeekStartDayEnumApi, zod.null()])
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
            .array(zod.string().max(projectBackwardCompatApiRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        person_on_events_querying_enabled: zod.boolean(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        default_modifiers: zod.record(zod.string(), zod.unknown()),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        product_intents: zod.array(
            zod.object({
                product_type: zod.string().optional(),
                created_at: zod.iso.datetime({ offset: true }).optional(),
                onboarding_completed_at: zod.iso.datetime({ offset: true }).nullish(),
                updated_at: zod.iso.datetime({ offset: true }).optional(),
            })
        ),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        secret_api_token: zod.string().nullable(),
        secret_api_token_backup: zod.string().nullable(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([BusinessModelEnumApi, BlankEnumApi, zod.null()])
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
        available_setup_task_ids: zod.array(AvailableSetupTaskIdsEnumApi),
        is_pending_deletion: zod
            .boolean()
            .nullable()
            .describe(
                'Set to True when project deletion has been initiated. Blocks UI access to this project until the async task completes.'
            ),
        project_id: zod.number().describe('ID of the project this environment belongs to.'),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
        managed_viewsets: zod.record(zod.string(), zod.boolean()),
        revenue_analytics_config: TeamRevenueAnalyticsConfigApi.optional(),
        marketing_analytics_config: TeamMarketingAnalyticsConfigApi.optional(),
        customer_analytics_config: TeamCustomerAnalyticsConfigApi.optional(),
        workflows_config: TeamWorkflowsConfigApi.optional(),
        base_currency: BaseCurrencyEnumApi.optional(),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod.union([CookielessServerHashModeEnumApi, zod.null()]).optional(),
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
            .min(projectBackwardCompatApiDefaultDataThemeMin)
            .max(projectBackwardCompatApiDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
        event_retention_months: zod
            .number()
            .describe(
                "The team's events data retention window in months (plan-derived, synced from billing). When retention enforcement is active for the team, queries do not return events older than this many months."
            ),
        events_retention_enforced: zod
            .boolean()
            .describe('Whether events data retention is currently enforced for this team (cohort\/flag gated).'),
    })
    .describe('Mixin for serializers to add user access control fields')

export type ProjectBackwardCompatApi = zod.input<typeof ProjectBackwardCompatApi>
export type ProjectBackwardCompatApiOutput = zod.output<typeof ProjectBackwardCompatApi>

export const patchedProjectBackwardCompatApiNameMax = 200

export const patchedProjectBackwardCompatApiProductDescriptionMax = 1000

export const patchedProjectBackwardCompatApiAppUrlsItemMax = 200

export const patchedProjectBackwardCompatApiPersonDisplayNamePropertiesItemMax = 400

export const patchedProjectBackwardCompatApiSessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const patchedProjectBackwardCompatApiSessionRecordingMinimumDurationMillisecondsMin = 0
export const patchedProjectBackwardCompatApiSessionRecordingMinimumDurationMillisecondsMax = 30000

export const patchedProjectBackwardCompatApiSessionRecordingTriggerMatchTypeConfigMax = 24

export const patchedProjectBackwardCompatApiRecordingDomainsItemMax = 200

export const patchedProjectBackwardCompatApiDefaultDataThemeMin = -2147483648
export const patchedProjectBackwardCompatApiDefaultDataThemeMax = 2147483647

export const PatchedProjectBackwardCompatApi = zod
    .object({
        id: zod.number().optional(),
        organization: zod.uuid().optional(),
        name: zod
            .string()
            .min(1)
            .max(patchedProjectBackwardCompatApiNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(patchedProjectBackwardCompatApiProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        effective_membership_level: EffectiveMembershipLevelEnumApi.optional(),
        has_group_types: zod.boolean().optional(),
        group_types: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
        live_events_token: zod.string().nullish(),
        updated_at: zod.iso.datetime({ offset: true }).nullish(),
        uuid: zod.uuid().optional(),
        api_token: zod.string().optional(),
        app_urls: zod.array(zod.string().max(patchedProjectBackwardCompatApiAppUrlsItemMax).nullable()).optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        ingested_event: zod.boolean().optional(),
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
            .array(zod.string().max(patchedProjectBackwardCompatApiPersonDisplayNamePropertiesItemMax))
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
            .stringFormat('decimal', patchedProjectBackwardCompatApiSessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(patchedProjectBackwardCompatApiSessionRecordingMinimumDurationMillisecondsMin)
            .max(patchedProjectBackwardCompatApiSessionRecordingMinimumDurationMillisecondsMax)
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
            .max(patchedProjectBackwardCompatApiSessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .optional()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: SessionRecordingRetentionPeriodEnumApi.optional().describe(
            'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n\* `30d` - 30 Days\n\* `90d` - 90 Days\n\* `1y` - 1 Year\n\* `5y` - 5 Years'
        ),
        session_replay_config: zod.unknown().optional(),
        survey_config: zod.unknown().optional(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([WeekStartDayEnumApi, zod.null()])
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
            .array(zod.string().max(patchedProjectBackwardCompatApiRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        person_on_events_querying_enabled: zod.boolean().optional(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().optional(),
        modifiers: zod.unknown().optional(),
        default_modifiers: zod.record(zod.string(), zod.unknown()).optional(),
        has_completed_onboarding_for: zod.unknown().optional(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        product_intents: zod
            .array(
                zod.object({
                    product_type: zod.string().optional(),
                    created_at: zod.iso.datetime({ offset: true }).optional(),
                    onboarding_completed_at: zod.iso.datetime({ offset: true }).nullish(),
                    updated_at: zod.iso.datetime({ offset: true }).optional(),
                })
            )
            .optional(),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        secret_api_token: zod.string().nullish(),
        secret_api_token_backup: zod.string().nullish(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([BusinessModelEnumApi, BlankEnumApi, zod.null()])
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
        available_setup_task_ids: zod.array(AvailableSetupTaskIdsEnumApi).optional(),
        is_pending_deletion: zod
            .boolean()
            .nullish()
            .describe(
                'Set to True when project deletion has been initiated. Blocks UI access to this project until the async task completes.'
            ),
        project_id: zod.number().optional().describe('ID of the project this environment belongs to.'),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
        managed_viewsets: zod.record(zod.string(), zod.boolean()).optional(),
        revenue_analytics_config: TeamRevenueAnalyticsConfigApi.optional(),
        marketing_analytics_config: TeamMarketingAnalyticsConfigApi.optional(),
        customer_analytics_config: TeamCustomerAnalyticsConfigApi.optional(),
        workflows_config: TeamWorkflowsConfigApi.optional(),
        base_currency: BaseCurrencyEnumApi.optional(),
        capture_dead_clicks: zod
            .boolean()
            .nullish()
            .describe('Enables capturing clicks that had no effect (rage-click detection).'),
        cookieless_server_hash_mode: zod.union([CookielessServerHashModeEnumApi, zod.null()]).optional(),
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
            .min(patchedProjectBackwardCompatApiDefaultDataThemeMin)
            .max(patchedProjectBackwardCompatApiDefaultDataThemeMax)
            .nullish(),
        onboarding_tasks: zod.unknown().optional(),
        web_analytics_pre_aggregated_tables_enabled: zod.boolean().nullish(),
        event_retention_months: zod
            .number()
            .optional()
            .describe(
                "The team's events data retention window in months (plan-derived, synced from billing). When retention enforcement is active for the team, queries do not return events older than this many months."
            ),
        events_retention_enforced: zod
            .boolean()
            .optional()
            .describe('Whether events data retention is currently enforced for this team (cohort\/flag gated).'),
    })
    .describe('Mixin for serializers to add user access control fields')

export type PatchedProjectBackwardCompatApi = zod.input<typeof PatchedProjectBackwardCompatApi>
export type PatchedProjectBackwardCompatApiOutput = zod.output<typeof PatchedProjectBackwardCompatApi>

export const sharePasswordApiNoteMax = 100

export const SharePasswordApi = zod.object({
    id: zod.number(),
    created_at: zod.iso.datetime({ offset: true }),
    note: zod.string().max(sharePasswordApiNoteMax).nullish(),
    created_by_email: zod.string(),
    is_active: zod.boolean(),
})

export type SharePasswordApi = zod.input<typeof SharePasswordApi>
export type SharePasswordApiOutput = zod.output<typeof SharePasswordApi>

export const SharingConfigurationApi = zod
    .object({
        created_at: zod.iso.datetime({ offset: true }),
        enabled: zod.boolean().optional(),
        access_token: zod.string().nullable(),
        settings: zod.unknown().optional(),
        password_required: zod.boolean().optional(),
        share_passwords: zod.array(SharePasswordApi),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Mixin for serializers to add user access control fields')

export type SharingConfigurationApi = zod.input<typeof SharingConfigurationApi>
export type SharingConfigurationApiOutput = zod.output<typeof SharingConfigurationApi>

export const fileSystemApiTypeMax = 100

export const fileSystemApiRefMax = 100

export const FileSystemApi = zod.object({
    id: zod.uuid(),
    path: zod.string(),
    depth: zod.number().nullable(),
    type: zod.string().max(fileSystemApiTypeMax).optional(),
    ref: zod.string().max(fileSystemApiRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: zod.union([UserBasicApi, zod.null()]),
    last_viewed_at: zod.iso.datetime({ offset: true }).nullable(),
    user_access_level: zod
        .string()
        .nullable()
        .describe(
            "Resolved access level the user has for the object this entry references ('none' means the user can't open it). Null when access controls don't apply to the entry type."
        ),
})

export type FileSystemApi = zod.input<typeof FileSystemApi>
export type FileSystemApiOutput = zod.output<typeof FileSystemApi>

export const PaginatedFileSystemListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(FileSystemApi),
})

export type PaginatedFileSystemListApi = zod.input<typeof PaginatedFileSystemListApi>
export type PaginatedFileSystemListApiOutput = zod.output<typeof PaginatedFileSystemListApi>

export const patchedFileSystemApiTypeMax = 100

export const patchedFileSystemApiRefMax = 100

export const PatchedFileSystemApi = zod.object({
    id: zod.uuid().optional(),
    path: zod.string().optional(),
    depth: zod.number().nullish(),
    type: zod.string().max(patchedFileSystemApiTypeMax).optional(),
    ref: zod.string().max(patchedFileSystemApiRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().optional(),
    shortcut: zod.boolean().nullish(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: zod.union([UserBasicApi, zod.null()]).optional(),
    last_viewed_at: zod.iso.datetime({ offset: true }).nullish(),
    user_access_level: zod
        .string()
        .nullish()
        .describe(
            "Resolved access level the user has for the object this entry references ('none' means the user can't open it). Null when access controls don't apply to the entry type."
        ),
})

export type PatchedFileSystemApi = zod.input<typeof PatchedFileSystemApi>
export type PatchedFileSystemApiOutput = zod.output<typeof PatchedFileSystemApi>

export const PatchedCanvasPublishApi = zod
    .object({
        code: zod.string().optional().describe('The complete single-file React source for the canvas.'),
        prompt: zod
            .string()
            .optional()
            .describe('Short description of the change, stored on the appended version history entry.'),
        name: zod
            .string()
            .optional()
            .describe('Optional new display name for the canvas (rewrites the leaf segment of its path).'),
        expected_current_version_id: zod
            .string()
            .nullish()
            .describe(
                "Optimistic-concurrency guard: the currentVersionId the publisher based its edits on (null when it read a canvas with no versions yet). When provided and the canvas has since moved past it (a concurrent publish, or a user's undo) the publish is rejected with a 409 version_conflict instead of overwriting the newer head. Omit to publish unguarded."
            ),
    })
    .describe("Payload for publishing a freeform canvas's React source via the agent.")

export type PatchedCanvasPublishApi = zod.input<typeof PatchedCanvasPublishApi>
export type PatchedCanvasPublishApiOutput = zod.output<typeof PatchedCanvasPublishApi>

export const CanvasPublishConflictApi = zod
    .object({
        detail: zod.string().describe('Human-readable description of the conflict and how to recover.'),
        code: zod.string().describe('Always \"version_conflict\".'),
        current_version_id: zod
            .string()
            .nullable()
            .describe("The canvas's live currentVersionId at rejection time (null when the canvas has no versions)."),
    })
    .describe('409 body for a guarded canvas publish based on a stale version.')

export type CanvasPublishConflictApi = zod.input<typeof CanvasPublishConflictApi>
export type CanvasPublishConflictApiOutput = zod.output<typeof CanvasPublishConflictApi>

export const ContextGenerationApi = zod.object({
    task_id: zod
        .uuid()
        .nullable()
        .describe("ID of the Task currently generating this folder's CONTEXT.md, or null if none."),
})

export type ContextGenerationApi = zod.input<typeof ContextGenerationApi>
export type ContextGenerationApiOutput = zod.output<typeof ContextGenerationApi>

export const ContextGenerationSetApi = zod.object({
    task_id: zod
        .uuid()
        .nullable()
        .describe(
            "ID of the Task generating this folder's CONTEXT.md. Must reference a Task in the same team. Set to null to clear the association."
        ),
})

export type ContextGenerationSetApi = zod.input<typeof ContextGenerationSetApi>
export type ContextGenerationSetApiOutput = zod.output<typeof ContextGenerationSetApi>

export const FolderInstructionsApi = zod.object({
    id: zod.uuid().describe('Unique identifier for this instructions version.'),
    content: zod.string().describe('Markdown instructions describing the contents of the folder.'),
    version: zod.number().describe('Monotonically increasing version number, starting at 1.'),
    is_latest: zod.boolean().describe('Whether this is the current (latest) version for the folder.'),
    created_by: UserBasicApi.describe('User who published this version.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When this version was published.'),
    updated_at: zod.iso.datetime({ offset: true }).describe('When this version row was last modified.'),
})

export type FolderInstructionsApi = zod.input<typeof FolderInstructionsApi>
export type FolderInstructionsApiOutput = zod.output<typeof FolderInstructionsApi>

export const folderInstructionsPublishApiBaseVersionMin = 0

export const FolderInstructionsPublishApi = zod.object({
    content: zod.string().describe('Full markdown instructions to publish as a new version for the folder.'),
    base_version: zod
        .number()
        .min(folderInstructionsPublishApiBaseVersionMin)
        .optional()
        .describe(
            "Latest version you are editing from, for optimistic concurrency. If provided and the folder's instructions have changed since, the request fails with 409. Use 0 when no instructions exist yet."
        ),
})

export type FolderInstructionsPublishApi = zod.input<typeof FolderInstructionsPublishApi>
export type FolderInstructionsPublishApiOutput = zod.output<typeof FolderInstructionsPublishApi>

export const patchedFolderInstructionsPublishApiBaseVersionMin = 0

export const PatchedFolderInstructionsPublishApi = zod.object({
    content: zod.string().optional().describe('Full markdown instructions to publish as a new version for the folder.'),
    base_version: zod
        .number()
        .min(patchedFolderInstructionsPublishApiBaseVersionMin)
        .optional()
        .describe(
            "Latest version you are editing from, for optimistic concurrency. If provided and the folder's instructions have changed since, the request fails with 409. Use 0 when no instructions exist yet."
        ),
})

export type PatchedFolderInstructionsPublishApi = zod.input<typeof PatchedFolderInstructionsPublishApi>
export type PatchedFolderInstructionsPublishApiOutput = zod.output<typeof PatchedFolderInstructionsPublishApi>

export const FolderInstructionsVersionApi = zod
    .object({
        id: zod.uuid().describe('Unique identifier for this instructions version.'),
        version: zod.number().describe('Monotonically increasing version number, starting at 1.'),
        is_latest: zod.boolean().describe('Whether this is the current (latest) version for the folder.'),
        created_by: UserBasicApi.describe('User who published this version.'),
        created_at: zod.iso.datetime({ offset: true }).describe('When this version was published.'),
    })
    .describe('Version-history entry: metadata only, with the markdown content omitted.')

export type FolderInstructionsVersionApi = zod.input<typeof FolderInstructionsVersionApi>
export type FolderInstructionsVersionApiOutput = zod.output<typeof FolderInstructionsVersionApi>

export const PaginatedFolderInstructionsVersionListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(FolderInstructionsVersionApi),
})

export type PaginatedFolderInstructionsVersionListApi = zod.input<typeof PaginatedFolderInstructionsVersionListApi>
export type PaginatedFolderInstructionsVersionListApiOutput = zod.output<
    typeof PaginatedFolderInstructionsVersionListApi
>

export const fileSystemShortcutApiTypeMax = 100

export const fileSystemShortcutApiRefMax = 100

export const fileSystemShortcutApiOrderMin = -2147483648
export const fileSystemShortcutApiOrderMax = 2147483647

export const FileSystemShortcutApi = zod.object({
    id: zod.uuid(),
    path: zod.string().describe('Display path of the shortcut in the sidebar.'),
    type: zod
        .string()
        .max(fileSystemShortcutApiTypeMax)
        .optional()
        .describe("Type of the linked item (e.g. 'folder', 'insight'), or blank."),
    ref: zod
        .string()
        .max(fileSystemShortcutApiRefMax)
        .nullish()
        .describe('Reference to the linked item, scoped to its type. Null for href-only shortcuts.'),
    href: zod
        .string()
        .nullish()
        .describe('Destination URL the shortcut opens. Null when the shortcut points at an item by ref.'),
    order: zod
        .number()
        .min(fileSystemShortcutApiOrderMin)
        .max(fileSystemShortcutApiOrderMax)
        .optional()
        .describe("Display order within the user's shortcut list, ascending."),
    created_at: zod.iso.datetime({ offset: true }),
    user_access_level: zod
        .string()
        .nullable()
        .describe(
            "Resolved access level the user has for the object this entry references ('none' means the user can't open it). Null when access controls don't apply to the entry type."
        ),
})

export type FileSystemShortcutApi = zod.input<typeof FileSystemShortcutApi>
export type FileSystemShortcutApiOutput = zod.output<typeof FileSystemShortcutApi>

export const PaginatedFileSystemShortcutListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(FileSystemShortcutApi),
})

export type PaginatedFileSystemShortcutListApi = zod.input<typeof PaginatedFileSystemShortcutListApi>
export type PaginatedFileSystemShortcutListApiOutput = zod.output<typeof PaginatedFileSystemShortcutListApi>

export const patchedFileSystemShortcutApiTypeMax = 100

export const patchedFileSystemShortcutApiRefMax = 100

export const patchedFileSystemShortcutApiOrderMin = -2147483648
export const patchedFileSystemShortcutApiOrderMax = 2147483647

export const PatchedFileSystemShortcutApi = zod.object({
    id: zod.uuid().optional(),
    path: zod.string().optional().describe('Display path of the shortcut in the sidebar.'),
    type: zod
        .string()
        .max(patchedFileSystemShortcutApiTypeMax)
        .optional()
        .describe("Type of the linked item (e.g. 'folder', 'insight'), or blank."),
    ref: zod
        .string()
        .max(patchedFileSystemShortcutApiRefMax)
        .nullish()
        .describe('Reference to the linked item, scoped to its type. Null for href-only shortcuts.'),
    href: zod
        .string()
        .nullish()
        .describe('Destination URL the shortcut opens. Null when the shortcut points at an item by ref.'),
    order: zod
        .number()
        .min(patchedFileSystemShortcutApiOrderMin)
        .max(patchedFileSystemShortcutApiOrderMax)
        .optional()
        .describe("Display order within the user's shortcut list, ascending."),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    user_access_level: zod
        .string()
        .nullish()
        .describe(
            "Resolved access level the user has for the object this entry references ('none' means the user can't open it). Null when access controls don't apply to the entry type."
        ),
})

export type PatchedFileSystemShortcutApi = zod.input<typeof PatchedFileSystemShortcutApi>
export type PatchedFileSystemShortcutApiOutput = zod.output<typeof PatchedFileSystemShortcutApi>

export const FileSystemShortcutReorderApi = zod.object({
    ordered_ids: zod.array(zod.uuid()).describe("IDs of the current user's shortcuts in the desired display order."),
})

export type FileSystemShortcutReorderApi = zod.input<typeof FileSystemShortcutReorderApi>
export type FileSystemShortcutReorderApiOutput = zod.output<typeof FileSystemShortcutReorderApi>

export const ExportFormatEnumApi = zod
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
    )

export type ExportFormatEnumApi = zod.input<typeof ExportFormatEnumApi>
export type ExportFormatEnumApiOutput = zod.output<typeof ExportFormatEnumApi>

export const ExportedAssetApi = zod
    .object({
        id: zod.number(),
        dashboard: zod.number().nullish(),
        insight: zod.number().nullish(),
        export_format: ExportFormatEnumApi,
        created_at: zod.iso.datetime({ offset: true }),
        has_content: zod.boolean(),
        export_context: zod.unknown().optional(),
        filename: zod.string(),
        expires_after: zod.iso.datetime({ offset: true }).nullable(),
        exception: zod.string().nullable(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe("Standard ExportedAsset serializer that doesn't return content.")

export type ExportedAssetApi = zod.input<typeof ExportedAssetApi>
export type ExportedAssetApiOutput = zod.output<typeof ExportedAssetApi>

export const PaginatedExportedAssetListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ExportedAssetApi),
})

export type PaginatedExportedAssetListApi = zod.input<typeof PaginatedExportedAssetListApi>
export type PaginatedExportedAssetListApiOutput = zod.output<typeof PaginatedExportedAssetListApi>

export const ProductsEnumApi = zod
    .enum(['conversations', 'error_tracking', 'session_replay'])
    .describe(
        '\* `conversations` - conversations\n\* `error_tracking` - error_tracking\n\* `session_replay` - session_replay'
    )

export type ProductsEnumApi = zod.input<typeof ProductsEnumApi>
export type ProductsEnumApiOutput = zod.output<typeof ProductsEnumApi>

export const ProductEnablementApi = zod.object({
    products: zod
        .array(ProductsEnumApi)
        .min(1)
        .describe('Products to turn on for this project, each enabled with server-owned conservative defaults.'),
})

export type ProductEnablementApi = zod.input<typeof ProductEnablementApi>
export type ProductEnablementApiOutput = zod.output<typeof ProductEnablementApi>

export const ProductEnablementResultApi = zod.object({
    results: zod
        .record(zod.string(), zod.string())
        .describe('Per requested product: \"enabled\" (just turned on) or \"already_enabled\".'),
})

export type ProductEnablementResultApi = zod.input<typeof ProductEnablementResultApi>
export type ProductEnablementResultApiOutput = zod.output<typeof ProductEnablementResultApi>

export const projectSecretAPIKeyApiLabelMax = 40

export const ProjectSecretAPIKeyApi = zod.object({
    id: zod.string(),
    label: zod.string().max(projectSecretAPIKeyApiLabelMax),
    value: zod.string(),
    mask_value: zod.string().nullable(),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    last_used_at: zod.iso.datetime({ offset: true }).nullable(),
    last_rolled_at: zod.iso.datetime({ offset: true }).nullable(),
    scopes: zod
        .array(zod.string())
        .describe(
            'Project-wide API scopes granted to this key. Project secret API keys do not honor object-level access controls, so a scope can access resources of that type even when per-resource RBAC would hide them from an individual user.'
        ),
})

export type ProjectSecretAPIKeyApi = zod.input<typeof ProjectSecretAPIKeyApi>
export type ProjectSecretAPIKeyApiOutput = zod.output<typeof ProjectSecretAPIKeyApi>

export const PaginatedProjectSecretAPIKeyListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ProjectSecretAPIKeyApi),
})

export type PaginatedProjectSecretAPIKeyListApi = zod.input<typeof PaginatedProjectSecretAPIKeyListApi>
export type PaginatedProjectSecretAPIKeyListApiOutput = zod.output<typeof PaginatedProjectSecretAPIKeyListApi>

export const patchedProjectSecretAPIKeyApiLabelMax = 40

export const PatchedProjectSecretAPIKeyApi = zod.object({
    id: zod.string().optional(),
    label: zod.string().max(patchedProjectSecretAPIKeyApiLabelMax).optional(),
    value: zod.string().optional(),
    mask_value: zod.string().nullish(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: UserBasicApi.optional(),
    last_used_at: zod.iso.datetime({ offset: true }).nullish(),
    last_rolled_at: zod.iso.datetime({ offset: true }).nullish(),
    scopes: zod
        .array(zod.string())
        .optional()
        .describe(
            'Project-wide API scopes granted to this key. Project secret API keys do not honor object-level access controls, so a scope can access resources of that type even when per-resource RBAC would hide them from an individual user.'
        ),
})

export type PatchedProjectSecretAPIKeyApi = zod.input<typeof PatchedProjectSecretAPIKeyApi>
export type PatchedProjectSecretAPIKeyApiOutput = zod.output<typeof PatchedProjectSecretAPIKeyApi>

export const PropertyDefinitionTypeEnumApi = zod
    .enum(['DateTime', 'String', 'Numeric', 'Boolean', 'Duration'])
    .describe(
        '\* `DateTime` - DateTime\n\* `String` - String\n\* `Numeric` - Numeric\n\* `Boolean` - Boolean\n\* `Duration` - Duration'
    )

export type PropertyDefinitionTypeEnumApi = zod.input<typeof PropertyDefinitionTypeEnumApi>
export type PropertyDefinitionTypeEnumApiOutput = zod.output<typeof PropertyDefinitionTypeEnumApi>

export const EnterprisePropertyDefinitionApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        is_numerical: zod.boolean(),
        updated_at: zod.iso.datetime({ offset: true }),
        updated_by: UserBasicApi,
        is_seen_on_filtered_events: zod.boolean().nullable(),
        property_type: zod.union([PropertyDefinitionTypeEnumApi, BlankEnumApi, zod.null()]).optional(),
        verified: zod.boolean().optional(),
        verified_at: zod.iso.datetime({ offset: true }).nullable(),
        verified_by: UserBasicApi,
        hidden: zod.boolean().nullish(),
        warehouse_origin: zod
            .unknown()
            .describe(
                'Provenance for a person property populated from a data warehouse source (source\/table\/column\/last synced), or null. Read-only.'
            ),
    })
    .describe('Serializer mixin that handles tags for objects.')

export type EnterprisePropertyDefinitionApi = zod.input<typeof EnterprisePropertyDefinitionApi>
export type EnterprisePropertyDefinitionApiOutput = zod.output<typeof EnterprisePropertyDefinitionApi>

export const PaginatedEnterprisePropertyDefinitionListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(EnterprisePropertyDefinitionApi),
})

export type PaginatedEnterprisePropertyDefinitionListApi = zod.input<
    typeof PaginatedEnterprisePropertyDefinitionListApi
>
export type PaginatedEnterprisePropertyDefinitionListApiOutput = zod.output<
    typeof PaginatedEnterprisePropertyDefinitionListApi
>

export const PatchedEnterprisePropertyDefinitionApi = zod
    .object({
        id: zod.uuid().optional(),
        name: zod.string().optional(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        is_numerical: zod.boolean().optional(),
        updated_at: zod.iso.datetime({ offset: true }).optional(),
        updated_by: UserBasicApi.optional(),
        is_seen_on_filtered_events: zod.boolean().nullish(),
        property_type: zod.union([PropertyDefinitionTypeEnumApi, BlankEnumApi, zod.null()]).optional(),
        verified: zod.boolean().optional(),
        verified_at: zod.iso.datetime({ offset: true }).nullish(),
        verified_by: UserBasicApi.optional(),
        hidden: zod.boolean().nullish(),
        warehouse_origin: zod
            .unknown()
            .optional()
            .describe(
                'Provenance for a person property populated from a data warehouse source (source\/table\/column\/last synced), or null. Read-only.'
            ),
    })
    .describe('Serializer mixin that handles tags for objects.')

export type PatchedEnterprisePropertyDefinitionApi = zod.input<typeof PatchedEnterprisePropertyDefinitionApi>
export type PatchedEnterprisePropertyDefinitionApiOutput = zod.output<typeof PatchedEnterprisePropertyDefinitionApi>

export const BulkUpdateTagsActionEnumApi = zod
    .enum(['add', 'remove', 'set'])
    .describe('\* `add` - add\n\* `remove` - remove\n\* `set` - set')

export type BulkUpdateTagsActionEnumApi = zod.input<typeof BulkUpdateTagsActionEnumApi>
export type BulkUpdateTagsActionEnumApiOutput = zod.output<typeof BulkUpdateTagsActionEnumApi>

export const bulkUpdateTagsRequestApiIdsMax = 500

export const BulkUpdateTagsRequestApi = zod.object({
    ids: zod.array(zod.number()).max(bulkUpdateTagsRequestApiIdsMax).describe('List of object IDs to update tags on.'),
    action: BulkUpdateTagsActionEnumApi.describe(
        "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n\* `add` - add\n\* `remove` - remove\n\* `set` - set"
    ),
    tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
})

export type BulkUpdateTagsRequestApi = zod.input<typeof BulkUpdateTagsRequestApi>
export type BulkUpdateTagsRequestApiOutput = zod.output<typeof BulkUpdateTagsRequestApi>

export const BulkUpdateTagsItemApi = zod.object({
    id: zod.number(),
    tags: zod.array(zod.string()),
})

export type BulkUpdateTagsItemApi = zod.input<typeof BulkUpdateTagsItemApi>
export type BulkUpdateTagsItemApiOutput = zod.output<typeof BulkUpdateTagsItemApi>

export const BulkUpdateTagsErrorApi = zod.object({
    id: zod.number(),
    reason: zod.string(),
})

export type BulkUpdateTagsErrorApi = zod.input<typeof BulkUpdateTagsErrorApi>
export type BulkUpdateTagsErrorApiOutput = zod.output<typeof BulkUpdateTagsErrorApi>

export const BulkUpdateTagsResponseApi = zod.object({
    updated: zod.array(BulkUpdateTagsItemApi),
    skipped: zod.array(BulkUpdateTagsErrorApi),
})

export type BulkUpdateTagsResponseApi = zod.input<typeof BulkUpdateTagsResponseApi>
export type BulkUpdateTagsResponseApiOutput = zod.output<typeof BulkUpdateTagsResponseApi>

export const ToolbarModeEnumApi = zod
    .enum(['disabled', 'toolbar'])
    .describe('\* `disabled` - disabled\n\* `toolbar` - toolbar')

export type ToolbarModeEnumApi = zod.input<typeof ToolbarModeEnumApi>
export type ToolbarModeEnumApiOutput = zod.output<typeof ToolbarModeEnumApi>

export const teamBasicApiProjectIdMin = -2147483648
export const teamBasicApiProjectIdMax = 2147483647

export const TeamBasicApi = zod
    .object({
        id: zod.number(),
        uuid: zod.uuid(),
        organization: zod.uuid(),
        project_id: zod.number().min(teamBasicApiProjectIdMin).max(teamBasicApiProjectIdMax),
        api_token: zod.string(),
        name: zod.string(),
        completed_snippet_onboarding: zod.boolean(),
        has_completed_onboarding_for: zod.unknown(),
        ingested_event: zod.boolean(),
        is_demo: zod.boolean(),
        timezone: zod.string(),
        access_control: zod.boolean(),
    })
    .describe(
        'Serializer for `Team` model with minimal attributes to speeed up loading and transfer times.\nAlso used for nested serializers.'
    )

export type TeamBasicApi = zod.input<typeof TeamBasicApi>
export type TeamBasicApiOutput = zod.output<typeof TeamBasicApi>

export const PluginsAccessLevelEnumApi = zod
    .union([zod.literal(0), zod.literal(3), zod.literal(6), zod.literal(9)])
    .describe('\* `0` - none\n\* `3` - config\n\* `6` - install\n\* `9` - root')

export type PluginsAccessLevelEnumApi = zod.input<typeof PluginsAccessLevelEnumApi>
export type PluginsAccessLevelEnumApiOutput = zod.output<typeof PluginsAccessLevelEnumApi>

export const DefaultExperimentStatsMethodEnumApi = zod
    .enum(['bayesian', 'frequentist'])
    .describe('\* `bayesian` - Bayesian\n\* `frequentist` - Frequentist')

export type DefaultExperimentStatsMethodEnumApi = zod.input<typeof DefaultExperimentStatsMethodEnumApi>
export type DefaultExperimentStatsMethodEnumApiOutput = zod.output<typeof DefaultExperimentStatsMethodEnumApi>

export const organizationApiNameMax = 64

export const organizationApiSlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')

export const OrganizationApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(organizationApiNameMax),
    slug: zod.string().regex(organizationApiSlugRegExp),
    logo_media_id: zod.uuid().nullish(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    membership_level: EffectiveMembershipLevelEnumApi,
    plugins_access_level: PluginsAccessLevelEnumApi,
    teams: zod.array(zod.record(zod.string(), zod.unknown())),
    projects: zod.array(zod.record(zod.string(), zod.unknown())),
    available_product_features: zod.array(zod.unknown()).nullable(),
    is_member_join_email_enabled: zod
        .boolean()
        .describe('Legacy field; member-join emails are controlled per user in account notification settings.'),
    metadata: zod.record(zod.string(), zod.string()),
    customer_id: zod.string().nullable(),
    enforce_2fa: zod.boolean().nullish(),
    members_can_invite: zod.boolean().nullish(),
    members_can_create_projects: zod
        .boolean()
        .nullish()
        .describe(
            'When True, organization members (below admin) are allowed to create new projects. Admins and owners can always create projects.'
        ),
    members_can_use_personal_api_keys: zod.boolean().optional(),
    members_can_see_org_members: zod
        .boolean()
        .optional()
        .describe(
            'When False, members (below admin) only see themselves in the members list and only project members in access control.'
        ),
    allow_publicly_shared_resources: zod.boolean().optional(),
    member_count: zod.number(),
    is_ai_data_processing_approved: zod.boolean().nullish(),
    is_ai_training_opted_in: zod
        .boolean()
        .nullish()
        .describe('When True, this organization allows its data to be used to train PostHog AI models.'),
    is_ai_training_locked: zod
        .boolean()
        .nullable()
        .describe('When True, the AI training opt-out setting cannot be modified through the UI or API.'),
    is_ai_training_cta_shown: zod
        .boolean()
        .nullable()
        .describe('When True, in-app callouts inviting members to enable AI training are shown.'),
    is_hipaa: zod.boolean().nullable(),
    default_experiment_stats_method: zod
        .union([DefaultExperimentStatsMethodEnumApi, BlankEnumApi, zod.null()])
        .optional()
        .describe(
            'Default statistical method for new experiments in this organization.\n\n\* `bayesian` - Bayesian\n\* `frequentist` - Frequentist'
        ),
    default_anonymize_ips: zod
        .boolean()
        .optional()
        .describe("Default setting for 'Discard client IP data' for new projects in this organization."),
    default_role_id: zod
        .string()
        .nullish()
        .describe('ID of the role to automatically assign to new members joining the organization'),
    is_active: zod.boolean().nullable().describe("Set this to 'No' to temporarily disable an organization."),
    is_not_active_reason: zod
        .string()
        .nullable()
        .describe(
            '(optional) reason for why the organization has been de-activated. This will be displayed to users on the web app.'
        ),
    is_pending_deletion: zod
        .boolean()
        .nullable()
        .describe(
            'Set to True when org deletion has been initiated. Blocks all UI access until the async task completes.'
        ),
})

export type OrganizationApi = zod.input<typeof OrganizationApi>
export type OrganizationApiOutput = zod.output<typeof OrganizationApi>

export const organizationBasicApiNameMax = 64

export const organizationBasicApiSlugMax = 48

export const organizationBasicApiSlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const organizationBasicApiIsNotActiveReasonMax = 200

export const OrganizationBasicApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(organizationBasicApiNameMax),
        slug: zod.string().max(organizationBasicApiSlugMax).regex(organizationBasicApiSlugRegExp),
        logo_media_id: zod.uuid().nullable(),
        membership_level: EffectiveMembershipLevelEnumApi,
        members_can_use_personal_api_keys: zod.boolean().optional(),
        is_active: zod.boolean().nullish().describe("Set this to 'No' to temporarily disable an organization."),
        is_not_active_reason: zod
            .string()
            .max(organizationBasicApiIsNotActiveReasonMax)
            .nullish()
            .describe(
                '(optional) reason for why the organization has been de-activated. This will be displayed to users on the web app.'
            ),
        is_pending_deletion: zod
            .boolean()
            .nullish()
            .describe(
                'Set to True when org deletion has been initiated. Blocks all UI access until the async task completes.'
            ),
    })
    .describe(
        'Serializer for `Organization` model with minimal attributes to speeed up loading and transfer times.\nAlso used for nested serializers.'
    )

export type OrganizationBasicApi = zod.input<typeof OrganizationBasicApi>
export type OrganizationBasicApiOutput = zod.output<typeof OrganizationBasicApi>

export const scenePersonalisationBasicApiSceneMax = 200

export const ScenePersonalisationBasicApi = zod.object({
    scene: zod.string().max(scenePersonalisationBasicApiSceneMax),
    dashboard: zod.number().nullish(),
})

export type ScenePersonalisationBasicApi = zod.input<typeof ScenePersonalisationBasicApi>
export type ScenePersonalisationBasicApiOutput = zod.output<typeof ScenePersonalisationBasicApi>

export const ThemeModeEnumApi = zod
    .enum(['light', 'dark', 'system'])
    .describe('\* `light` - Light\n\* `dark` - Dark\n\* `system` - System')

export type ThemeModeEnumApi = zod.input<typeof ThemeModeEnumApi>
export type ThemeModeEnumApiOutput = zod.output<typeof ThemeModeEnumApi>

export const ShortcutPositionEnumApi = zod
    .enum(['above', 'below', 'hidden'])
    .describe('\* `above` - Above\n\* `below` - Below\n\* `hidden` - Hidden')

export type ShortcutPositionEnumApi = zod.input<typeof ShortcutPositionEnumApi>
export type ShortcutPositionEnumApiOutput = zod.output<typeof ShortcutPositionEnumApi>

export const OnboardingSkippedReasonEnumApi = zod
    .enum(['delegated', 'later', 'other', 'provisioned'])
    .describe(
        '\* `delegated` - Delegated to teammate\n\* `later` - Skipped for later\n\* `other` - Other\n\* `provisioned` - Account provisioned by a partner'
    )

export type OnboardingSkippedReasonEnumApi = zod.input<typeof OnboardingSkippedReasonEnumApi>
export type OnboardingSkippedReasonEnumApiOutput = zod.output<typeof OnboardingSkippedReasonEnumApi>

export const PendingInviteApi = zod
    .object({
        id: zod.string(),
        target_email: zod.email(),
        organization_id: zod.string(),
        organization_name: zod.string(),
        created_at: zod.iso.datetime({ offset: true }),
    })
    .describe('Shape of each item in UserSerializer.pending_invites.')

export type PendingInviteApi = zod.input<typeof PendingInviteApi>
export type PendingInviteApiOutput = zod.output<typeof PendingInviteApi>

export const userApiFirstNameMax = 150

export const userApiLastNameMax = 150

export const userApiEmailMax = 254

export const userApiPasswordMax = 128

export const UserApi = zod.object({
    date_joined: zod.iso.datetime({ offset: true }),
    uuid: zod.uuid(),
    distinct_id: zod.string().nullable(),
    first_name: zod.string().max(userApiFirstNameMax).optional(),
    last_name: zod.string().max(userApiLastNameMax).optional(),
    email: zod.email().max(userApiEmailMax),
    pending_email: zod.email().nullable(),
    is_email_verified: zod.boolean().nullable(),
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
    toolbar_mode: zod.union([ToolbarModeEnumApi, BlankEnumApi, zod.null()]).optional(),
    has_password: zod.boolean(),
    id: zod.number(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    is_impersonated: zod.boolean().nullable(),
    is_impersonated_until: zod.string().nullable(),
    is_impersonated_read_only: zod.boolean().nullable(),
    is_impersonated_reason: zod
        .string()
        .nullable()
        .describe(
            'The reason the operator gave when the current impersonation session started (or was last up\/downgraded). Null when not impersonating.'
        ),
    sensitive_session_expires_at: zod.string().nullable(),
    team: TeamBasicApi,
    organization: OrganizationApi,
    organizations: zod.array(OrganizationBasicApi),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(userApiPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    is_2fa_enabled: zod.boolean(),
    has_social_auth: zod.boolean(),
    has_sso_enforcement: zod.boolean(),
    has_seen_product_intro_for: zod.unknown().optional(),
    scene_personalisation: zod.array(ScenePersonalisationBasicApi),
    theme_mode: zod.union([ThemeModeEnumApi, BlankEnumApi, zod.null()]).optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod.union([ShortcutPositionEnumApi, BlankEnumApi, zod.null()]).optional(),
    role_at_organization: RoleAtOrganizationEnumApi.optional(),
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
    ui_configuration: zod
        .unknown()
        .optional()
        .describe(
            'Per-user UI customization, validated against the `UserUIConfiguration` schema. Currently covers sidebar section and item visibility. Send the complete object: it replaces the stored value wholesale. Null means no customization; absent keys mean the element is shown.'
        ),
    onboarding_skipped_at: zod.iso.datetime({ offset: true }).nullable(),
    onboarding_skipped_reason: zod.union([OnboardingSkippedReasonEnumApi, zod.null()]),
    onboarding_skipped_organization_id: zod.uuid().nullable(),
    onboarding_delegated_to_invite: zod.uuid().nullable(),
    onboarding_delegated_to_organization_id: zod
        .uuid()
        .nullable()
        .describe(
            "Organization ID of the pending delegation invite, if any. Used by the frontend to scope the 'waiting for teammate' UI to the org where delegation was initiated."
        ),
    onboarding_delegation_accepted_at: zod.iso.datetime({ offset: true }).nullable(),
    is_organization_first_user: zod.boolean().nullable(),
    active_realtime_notification_types: zod
        .array(zod.string())
        .describe(
            'Real-time notification types that currently have a live dispatch site. Drives the in-app notifications settings UI. Read-only.'
        ),
    pending_invites: zod.array(PendingInviteApi),
    requires_credential_review: zod
        .boolean()
        .describe(
            'True if the user has at least one Personal API Key or passkey and has not yet acknowledged their existing credentials. Used to gate a one-shot review screen on first post-provisioning login. Becomes False once the user POSTs to `\/api\/users\/@me\/credentials_review_complete\/`. Read-only.'
        ),
})

export type UserApi = zod.input<typeof UserApi>
export type UserApiOutput = zod.output<typeof UserApi>

export const PaginatedUserListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(UserApi),
})

export type PaginatedUserListApi = zod.input<typeof PaginatedUserListApi>
export type PaginatedUserListApiOutput = zod.output<typeof PaginatedUserListApi>

export const patchedUserApiFirstNameMax = 150

export const patchedUserApiLastNameMax = 150

export const patchedUserApiEmailMax = 254

export const patchedUserApiPasswordMax = 128

export const PatchedUserApi = zod.object({
    date_joined: zod.iso.datetime({ offset: true }).optional(),
    uuid: zod.uuid().optional(),
    distinct_id: zod.string().nullish(),
    first_name: zod.string().max(patchedUserApiFirstNameMax).optional(),
    last_name: zod.string().max(patchedUserApiLastNameMax).optional(),
    email: zod.email().max(patchedUserApiEmailMax).optional(),
    pending_email: zod.email().nullish(),
    is_email_verified: zod.boolean().nullish(),
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
    toolbar_mode: zod.union([ToolbarModeEnumApi, BlankEnumApi, zod.null()]).optional(),
    has_password: zod.boolean().optional(),
    id: zod.number().optional(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    is_impersonated: zod.boolean().nullish(),
    is_impersonated_until: zod.string().nullish(),
    is_impersonated_read_only: zod.boolean().nullish(),
    is_impersonated_reason: zod
        .string()
        .nullish()
        .describe(
            'The reason the operator gave when the current impersonation session started (or was last up\/downgraded). Null when not impersonating.'
        ),
    sensitive_session_expires_at: zod.string().nullish(),
    team: TeamBasicApi.optional(),
    organization: OrganizationApi.optional(),
    organizations: zod.array(OrganizationBasicApi).optional(),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(patchedUserApiPasswordMax).optional(),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    is_2fa_enabled: zod.boolean().optional(),
    has_social_auth: zod.boolean().optional(),
    has_sso_enforcement: zod.boolean().optional(),
    has_seen_product_intro_for: zod.unknown().optional(),
    scene_personalisation: zod.array(ScenePersonalisationBasicApi).optional(),
    theme_mode: zod.union([ThemeModeEnumApi, BlankEnumApi, zod.null()]).optional(),
    hedgehog_config: zod.unknown().optional(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod.union([ShortcutPositionEnumApi, BlankEnumApi, zod.null()]).optional(),
    role_at_organization: RoleAtOrganizationEnumApi.optional(),
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
    ui_configuration: zod
        .unknown()
        .optional()
        .describe(
            'Per-user UI customization, validated against the `UserUIConfiguration` schema. Currently covers sidebar section and item visibility. Send the complete object: it replaces the stored value wholesale. Null means no customization; absent keys mean the element is shown.'
        ),
    onboarding_skipped_at: zod.iso.datetime({ offset: true }).nullish(),
    onboarding_skipped_reason: zod.union([OnboardingSkippedReasonEnumApi, zod.null()]).optional(),
    onboarding_skipped_organization_id: zod.uuid().nullish(),
    onboarding_delegated_to_invite: zod.uuid().nullish(),
    onboarding_delegated_to_organization_id: zod
        .uuid()
        .nullish()
        .describe(
            "Organization ID of the pending delegation invite, if any. Used by the frontend to scope the 'waiting for teammate' UI to the org where delegation was initiated."
        ),
    onboarding_delegation_accepted_at: zod.iso.datetime({ offset: true }).nullish(),
    is_organization_first_user: zod.boolean().nullish(),
    active_realtime_notification_types: zod
        .array(zod.string())
        .optional()
        .describe(
            'Real-time notification types that currently have a live dispatch site. Drives the in-app notifications settings UI. Read-only.'
        ),
    pending_invites: zod.array(PendingInviteApi).optional(),
    requires_credential_review: zod
        .boolean()
        .optional()
        .describe(
            'True if the user has at least one Personal API Key or passkey and has not yet acknowledged their existing credentials. Used to gate a one-shot review screen on first post-provisioning login. Becomes False once the user POSTs to `\/api\/users\/@me\/credentials_review_complete\/`. Read-only.'
        ),
})

export type PatchedUserApi = zod.input<typeof PatchedUserApi>
export type PatchedUserApiOutput = zod.output<typeof PatchedUserApi>

export const UserGitHubAccountApi = zod.object({
    type: zod.string().nullish().describe('GitHub account type for the installation (e.g. User or Organization).'),
    name: zod.string().nullish().describe('GitHub login or organization name tied to the installation.'),
})

export type UserGitHubAccountApi = zod.input<typeof UserGitHubAccountApi>
export type UserGitHubAccountApiOutput = zod.output<typeof UserGitHubAccountApi>

export const UserGitHubIntegrationItemApi = zod.object({
    id: zod.uuid().describe('PostHog UserIntegration row id.'),
    kind: zod.string().describe('Integration kind; always `github` for this API.'),
    installation_id: zod.string().describe('GitHub App installation id.'),
    repository_selection: zod
        .string()
        .nullish()
        .describe('Repository selection mode from GitHub (e.g. selected or all).'),
    account: zod
        .union([UserGitHubAccountApi, zod.null()])
        .optional()
        .describe('Installation account metadata from GitHub.'),
    github_login: zod
        .string()
        .nullish()
        .describe("The connected user's own GitHub login (distinct from the installation account)."),
    uses_shared_installation: zod
        .boolean()
        .describe('True when this installation id matches a team-level GitHub integration on the active project.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When this integration row was created.'),
})

export type UserGitHubIntegrationItemApi = zod.input<typeof UserGitHubIntegrationItemApi>
export type UserGitHubIntegrationItemApiOutput = zod.output<typeof UserGitHubIntegrationItemApi>

export const UserGitHubIntegrationListResponseApi = zod.object({
    results: zod
        .array(UserGitHubIntegrationItemApi)
        .describe('GitHub personal integrations for the authenticated user.'),
})

export type UserGitHubIntegrationListResponseApi = zod.input<typeof UserGitHubIntegrationListResponseApi>
export type UserGitHubIntegrationListResponseApiOutput = zod.output<typeof UserGitHubIntegrationListResponseApi>

export const PaginatedUserGitHubIntegrationListResponseListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(UserGitHubIntegrationListResponseApi),
})

export type PaginatedUserGitHubIntegrationListResponseListApi = zod.input<
    typeof PaginatedUserGitHubIntegrationListResponseListApi
>
export type PaginatedUserGitHubIntegrationListResponseListApiOutput = zod.output<
    typeof PaginatedUserGitHubIntegrationListResponseListApi
>

export const GitHubBranchesResponseApi = zod.object({
    branches: zod.array(zod.string()).describe('List of branch names'),
    default_branch: zod.string().nullish().describe('The default branch of the repository'),
    has_more: zod.boolean().describe('Whether more branches exist beyond the returned page'),
})

export type GitHubBranchesResponseApi = zod.input<typeof GitHubBranchesResponseApi>
export type GitHubBranchesResponseApiOutput = zod.output<typeof GitHubBranchesResponseApi>

export const GitHubRepoApi = zod.object({
    id: zod.number().describe('GitHub repository numeric identifier.'),
    name: zod.string().describe('Repository short name (without the owner prefix).'),
    full_name: zod.string().describe("Fully-qualified repository name as 'owner\/repo'."),
    private: zod.boolean().optional().describe('Whether the repository is private.'),
    default_branch: zod.string().optional().describe("The repository's default branch (e.g. 'main')."),
    language: zod.string().optional().describe('Primary programming language GitHub detected for the repository.'),
    pushed_at: zod
        .string()
        .optional()
        .describe('ISO 8601 timestamp of the most recent push, useful for sorting by recent activity.'),
    archived: zod.boolean().optional().describe('Whether the repository is archived.'),
    can_push: zod
        .boolean()
        .optional()
        .describe('Whether the PostHog GitHub App has write access — required to open pull requests.'),
})

export type GitHubRepoApi = zod.input<typeof GitHubRepoApi>
export type GitHubRepoApiOutput = zod.output<typeof GitHubRepoApi>

export const GitHubReposResponseApi = zod.object({
    repositories: zod.array(GitHubRepoApi),
    has_more: zod.boolean().describe('Whether more repositories are available beyond this page.'),
})

export type GitHubReposResponseApi = zod.input<typeof GitHubReposResponseApi>
export type GitHubReposResponseApiOutput = zod.output<typeof GitHubReposResponseApi>

export const GitHubReposRefreshResponseApi = zod.object({
    repositories: zod.array(GitHubRepoApi).describe('The refreshed repository cache.'),
})

export type GitHubReposRefreshResponseApi = zod.input<typeof GitHubReposRefreshResponseApi>
export type GitHubReposRefreshResponseApiOutput = zod.output<typeof GitHubReposRefreshResponseApi>

export const UserGitHubPrepareCallbackRequestApi = zod.object({
    installation_id: zod.string().describe('GitHub App installation id being managed on github.com.'),
})

export type UserGitHubPrepareCallbackRequestApi = zod.input<typeof UserGitHubPrepareCallbackRequestApi>
export type UserGitHubPrepareCallbackRequestApiOutput = zod.output<typeof UserGitHubPrepareCallbackRequestApi>

export const UserGitHubLinkStartRequestApi = zod.object({
    team_id: zod
        .number()
        .nullish()
        .describe("Optional team\/project id (e.g. PostHog Desktop); web UI uses the session's current team."),
    connect_from: zod
        .string()
        .optional()
        .describe('Optional client hint (e.g. posthog_code) for return routing after OAuth.'),
})

export type UserGitHubLinkStartRequestApi = zod.input<typeof UserGitHubLinkStartRequestApi>
export type UserGitHubLinkStartRequestApiOutput = zod.output<typeof UserGitHubLinkStartRequestApi>

export const UserGitHubLinkStartResponseApi = zod.object({
    install_url: zod
        .string()
        .describe('URL to open in the browser to install or authorize the GitHub App for this user.'),
    connect_flow: zod.string().describe('OAuth or install flow used for this GitHub connection.'),
})

export type UserGitHubLinkStartResponseApi = zod.input<typeof UserGitHubLinkStartResponseApi>
export type UserGitHubLinkStartResponseApiOutput = zod.output<typeof UserGitHubLinkStartResponseApi>

export const UserSlackLinkableWorkspaceItemApi = zod.object({
    posthog_team_id: zod.number().describe('PostHog team\/project id owning the Slack workspace install.'),
    posthog_team_name: zod.string().describe('PostHog team\/project name, for display in a picker.'),
    posthog_organization_name: zod
        .string()
        .describe('PostHog organization name owning the team, for picker disambiguation.'),
    slack_team_id: zod.string().describe('Slack workspace (team) id.'),
    slack_team_name: zod.string().nullish().describe('Slack workspace display name as known by PostHog.'),
})

export type UserSlackLinkableWorkspaceItemApi = zod.input<typeof UserSlackLinkableWorkspaceItemApi>
export type UserSlackLinkableWorkspaceItemApiOutput = zod.output<typeof UserSlackLinkableWorkspaceItemApi>

export const UserSlackLinkableWorkspaceListResponseApi = zod.object({
    results: zod
        .array(UserSlackLinkableWorkspaceItemApi)
        .describe("Slack workspaces the user could link to but hasn't yet."),
})

export type UserSlackLinkableWorkspaceListResponseApi = zod.input<typeof UserSlackLinkableWorkspaceListResponseApi>
export type UserSlackLinkableWorkspaceListResponseApiOutput = zod.output<
    typeof UserSlackLinkableWorkspaceListResponseApi
>

export const UserSlackLinkStartRequestApi = zod
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

export type UserSlackLinkStartRequestApi = zod.input<typeof UserSlackLinkStartRequestApi>
export type UserSlackLinkStartRequestApiOutput = zod.output<typeof UserSlackLinkStartRequestApi>

export const UserSlackLinkStartResponseApi = zod.object({
    install_url: zod.string().describe('URL to open in the browser to start the Sign-in-with-Slack flow.'),
})

export type UserSlackLinkStartResponseApi = zod.input<typeof UserSlackLinkStartResponseApi>
export type UserSlackLinkStartResponseApiOutput = zod.output<typeof UserSlackLinkStartResponseApi>

export const UserAuthSessionApi = zod
    .object({
        id: zod.uuid().describe('Identifier used to revoke this login session.'),
        created_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When this login session was first created — the original sign-in time.'),
        last_activity: zod.iso
            .datetime({ offset: true })
            .describe('When this login session last made a request (refreshed periodically).'),
        location: zod.string().describe('Approximate city and country derived from the IP address, if known.'),
        device: zod
            .string()
            .describe("Browser and operating system parsed from the user agent, e.g. 'Chrome 135 on macOS'."),
        login_method: zod.string().describe('How this session signed in (e.g. password, Google, SAML).'),
        is_current: zod.boolean().describe('Whether this is the login session making the current request.'),
    })
    .describe("A cookie-auth login session shown on the user's 'Web sessions' screen.")

export type UserAuthSessionApi = zod.input<typeof UserAuthSessionApi>
export type UserAuthSessionApiOutput = zod.output<typeof UserAuthSessionApi>

export const RevokeOtherSessionsResponseApi = zod.object({
    revoked_count: zod.number().describe('Number of other login sessions that were revoked.'),
})

export type RevokeOtherSessionsResponseApi = zod.input<typeof RevokeOtherSessionsResponseApi>
export type RevokeOtherSessionsResponseApiOutput = zod.output<typeof RevokeOtherSessionsResponseApi>

export const OnboardingSkipRequestReasonEnumApi = zod
    .enum(['later', 'other'])
    .describe('\* `later` - Later\n\* `other` - Other')

export type OnboardingSkipRequestReasonEnumApi = zod.input<typeof OnboardingSkipRequestReasonEnumApi>
export type OnboardingSkipRequestReasonEnumApiOutput = zod.output<typeof OnboardingSkipRequestReasonEnumApi>

export const onboardingSkipRequestApiStepAtSkipMax = 64

export const OnboardingSkipRequestApi = zod
    .object({
        reason: OnboardingSkipRequestReasonEnumApi.describe(
            "Why the user is leaving onboarding. 'later' keeps them able to return; 'other' is a catch-all. 'delegated' is rejected here — use the delegate endpoint so the delegation invite is created atomically.\n\n\* `later` - Later\n\* `other` - Other"
        ),
        step_at_skip: zod
            .string()
            .max(onboardingSkipRequestApiStepAtSkipMax)
            .optional()
            .describe('Onboarding step key the user was on when skipping, for analytics only.'),
    })
    .describe(
        'Request body for POST \/api\/users\/{id}\/onboarding\/skip\/.\n\nSource of truth for OpenAPI \/ generated TS \/ zod \/ MCP — bind this serializer at\nruntime so the contract clients believe is enforced (length cap, choice validation,\nno extra fields) is actually enforced server-side.'
    )

export type OnboardingSkipRequestApi = zod.input<typeof OnboardingSkipRequestApi>
export type OnboardingSkipRequestApiOutput = zod.output<typeof OnboardingSkipRequestApi>

export const PushTokenPlatformEnumApi = zod
    .enum(['ios', 'android', 'web'])
    .describe('\* `ios` - iOS\n\* `android` - Android\n\* `web` - Web')

export type PushTokenPlatformEnumApi = zod.input<typeof PushTokenPlatformEnumApi>
export type PushTokenPlatformEnumApiOutput = zod.output<typeof PushTokenPlatformEnumApi>

export const userPushTokenRegisterRequestApiTokenMax = 512

export const UserPushTokenRegisterRequestApi = zod.object({
    token: zod
        .string()
        .max(userPushTokenRegisterRequestApiTokenMax)
        .describe("Opaque push token issued by the device's platform push service (e.g. an Expo push token)."),
    platform: PushTokenPlatformEnumApi.describe(
        'Device platform the token was issued for. One of `ios`, `android`, or `web`.\n\n\* `ios` - iOS\n\* `android` - Android\n\* `web` - Web'
    ),
})

export type UserPushTokenRegisterRequestApi = zod.input<typeof UserPushTokenRegisterRequestApi>
export type UserPushTokenRegisterRequestApiOutput = zod.output<typeof UserPushTokenRegisterRequestApi>

export const UserPushTokenItemApi = zod.object({
    id: zod.uuid().describe('PostHog UserPushToken row id.'),
    platform: PushTokenPlatformEnumApi.describe(
        'Device platform the token was issued for.\n\n\* `ios` - iOS\n\* `android` - Android\n\* `web` - Web'
    ),
    created_at: zod.iso.datetime({ offset: true }).describe('When this token was first registered.'),
    last_seen_at: zod.iso.datetime({ offset: true }).describe('Last time the mobile app re-registered this token.'),
})

export type UserPushTokenItemApi = zod.input<typeof UserPushTokenItemApi>
export type UserPushTokenItemApiOutput = zod.output<typeof UserPushTokenItemApi>

export const userPushTokenUnregisterRequestApiTokenMax = 512

export const UserPushTokenUnregisterRequestApi = zod.object({
    token: zod
        .string()
        .max(userPushTokenUnregisterRequestApiTokenMax)
        .describe('The opaque push token to remove for the authenticated user.'),
})

export type UserPushTokenUnregisterRequestApi = zod.input<typeof UserPushTokenUnregisterRequestApi>
export type UserPushTokenUnregisterRequestApiOutput = zod.output<typeof UserPushTokenUnregisterRequestApi>
