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

export const domainsListResponseResultsItemDomainMax = 128

export const domainsListResponseResultsItemSsoEnforcementMax = 28

export const domainsListResponseResultsItemSamlEntityIdMax = 512

export const domainsListResponseResultsItemSamlAcsUrlMax = 512

export const DomainsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            domain: zod.string().max(domainsListResponseResultsItemDomainMax),
            is_verified: zod.boolean().describe('Determines whether a domain is verified or not.'),
            verified_at: zod.iso.datetime({}).nullable(),
            verification_challenge: zod.string(),
            jit_provisioning_enabled: zod.boolean().optional(),
            sso_enforcement: zod.string().max(domainsListResponseResultsItemSsoEnforcementMax).optional(),
            has_saml: zod
                .boolean()
                .describe(
                    'Returns whether SAML is configured for the instance. Does not validate the user has the required license (that check is performed in other places).'
                ),
            saml_entity_id: zod.string().max(domainsListResponseResultsItemSamlEntityIdMax).nullish(),
            saml_acs_url: zod.string().max(domainsListResponseResultsItemSamlAcsUrlMax).nullish(),
            saml_x509_cert: zod.string().nullish(),
            has_scim: zod.boolean().describe('Returns whether SCIM is configured and enabled for this domain.'),
            scim_enabled: zod.boolean().optional(),
            scim_base_url: zod.string().nullable(),
            scim_bearer_token: zod.string().nullable(),
        })
    ),
})

export const domainsCreateBodyDomainMax = 128

export const domainsCreateBodySsoEnforcementMax = 28

export const domainsCreateBodySamlEntityIdMax = 512

export const domainsCreateBodySamlAcsUrlMax = 512

export const DomainsCreateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsCreateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsCreateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod.string().max(domainsCreateBodySamlEntityIdMax).nullish(),
    saml_acs_url: zod.string().max(domainsCreateBodySamlAcsUrlMax).nullish(),
    saml_x509_cert: zod.string().nullish(),
    scim_enabled: zod.boolean().optional(),
})

export const domainsRetrieveResponseDomainMax = 128

export const domainsRetrieveResponseSsoEnforcementMax = 28

export const domainsRetrieveResponseSamlEntityIdMax = 512

export const domainsRetrieveResponseSamlAcsUrlMax = 512

export const DomainsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    domain: zod.string().max(domainsRetrieveResponseDomainMax),
    is_verified: zod.boolean().describe('Determines whether a domain is verified or not.'),
    verified_at: zod.iso.datetime({}).nullable(),
    verification_challenge: zod.string(),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsRetrieveResponseSsoEnforcementMax).optional(),
    has_saml: zod
        .boolean()
        .describe(
            'Returns whether SAML is configured for the instance. Does not validate the user has the required license (that check is performed in other places).'
        ),
    saml_entity_id: zod.string().max(domainsRetrieveResponseSamlEntityIdMax).nullish(),
    saml_acs_url: zod.string().max(domainsRetrieveResponseSamlAcsUrlMax).nullish(),
    saml_x509_cert: zod.string().nullish(),
    has_scim: zod.boolean().describe('Returns whether SCIM is configured and enabled for this domain.'),
    scim_enabled: zod.boolean().optional(),
    scim_base_url: zod.string().nullable(),
    scim_bearer_token: zod.string().nullable(),
})

export const domainsUpdateBodyDomainMax = 128

export const domainsUpdateBodySsoEnforcementMax = 28

export const domainsUpdateBodySamlEntityIdMax = 512

export const domainsUpdateBodySamlAcsUrlMax = 512

export const DomainsUpdateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsUpdateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsUpdateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod.string().max(domainsUpdateBodySamlEntityIdMax).nullish(),
    saml_acs_url: zod.string().max(domainsUpdateBodySamlAcsUrlMax).nullish(),
    saml_x509_cert: zod.string().nullish(),
    scim_enabled: zod.boolean().optional(),
})

export const domainsUpdateResponseDomainMax = 128

export const domainsUpdateResponseSsoEnforcementMax = 28

export const domainsUpdateResponseSamlEntityIdMax = 512

export const domainsUpdateResponseSamlAcsUrlMax = 512

export const DomainsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    domain: zod.string().max(domainsUpdateResponseDomainMax),
    is_verified: zod.boolean().describe('Determines whether a domain is verified or not.'),
    verified_at: zod.iso.datetime({}).nullable(),
    verification_challenge: zod.string(),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsUpdateResponseSsoEnforcementMax).optional(),
    has_saml: zod
        .boolean()
        .describe(
            'Returns whether SAML is configured for the instance. Does not validate the user has the required license (that check is performed in other places).'
        ),
    saml_entity_id: zod.string().max(domainsUpdateResponseSamlEntityIdMax).nullish(),
    saml_acs_url: zod.string().max(domainsUpdateResponseSamlAcsUrlMax).nullish(),
    saml_x509_cert: zod.string().nullish(),
    has_scim: zod.boolean().describe('Returns whether SCIM is configured and enabled for this domain.'),
    scim_enabled: zod.boolean().optional(),
    scim_base_url: zod.string().nullable(),
    scim_bearer_token: zod.string().nullable(),
})

export const domainsPartialUpdateBodyDomainMax = 128

export const domainsPartialUpdateBodySsoEnforcementMax = 28

export const domainsPartialUpdateBodySamlEntityIdMax = 512

export const domainsPartialUpdateBodySamlAcsUrlMax = 512

export const DomainsPartialUpdateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsPartialUpdateBodyDomainMax).optional(),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsPartialUpdateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod.string().max(domainsPartialUpdateBodySamlEntityIdMax).nullish(),
    saml_acs_url: zod.string().max(domainsPartialUpdateBodySamlAcsUrlMax).nullish(),
    saml_x509_cert: zod.string().nullish(),
    scim_enabled: zod.boolean().optional(),
})

export const domainsPartialUpdateResponseDomainMax = 128

export const domainsPartialUpdateResponseSsoEnforcementMax = 28

export const domainsPartialUpdateResponseSamlEntityIdMax = 512

export const domainsPartialUpdateResponseSamlAcsUrlMax = 512

export const DomainsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    domain: zod.string().max(domainsPartialUpdateResponseDomainMax),
    is_verified: zod.boolean().describe('Determines whether a domain is verified or not.'),
    verified_at: zod.iso.datetime({}).nullable(),
    verification_challenge: zod.string(),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsPartialUpdateResponseSsoEnforcementMax).optional(),
    has_saml: zod
        .boolean()
        .describe(
            'Returns whether SAML is configured for the instance. Does not validate the user has the required license (that check is performed in other places).'
        ),
    saml_entity_id: zod.string().max(domainsPartialUpdateResponseSamlEntityIdMax).nullish(),
    saml_acs_url: zod.string().max(domainsPartialUpdateResponseSamlAcsUrlMax).nullish(),
    saml_x509_cert: zod.string().nullish(),
    has_scim: zod.boolean().describe('Returns whether SCIM is configured and enabled for this domain.'),
    scim_enabled: zod.boolean().optional(),
    scim_base_url: zod.string().nullable(),
    scim_bearer_token: zod.string().nullable(),
})

/**
 * Regenerate SCIM bearer token.
 */
export const domainsScimTokenCreateBodyDomainMax = 128

export const domainsScimTokenCreateBodySsoEnforcementMax = 28

export const domainsScimTokenCreateBodySamlEntityIdMax = 512

export const domainsScimTokenCreateBodySamlAcsUrlMax = 512

export const DomainsScimTokenCreateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsScimTokenCreateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsScimTokenCreateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod.string().max(domainsScimTokenCreateBodySamlEntityIdMax).nullish(),
    saml_acs_url: zod.string().max(domainsScimTokenCreateBodySamlAcsUrlMax).nullish(),
    saml_x509_cert: zod.string().nullish(),
    scim_enabled: zod.boolean().optional(),
})

export const domainsVerifyCreateBodyDomainMax = 128

export const domainsVerifyCreateBodySsoEnforcementMax = 28

export const domainsVerifyCreateBodySamlEntityIdMax = 512

export const domainsVerifyCreateBodySamlAcsUrlMax = 512

export const DomainsVerifyCreateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsVerifyCreateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsVerifyCreateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod.string().max(domainsVerifyCreateBodySamlEntityIdMax).nullish(),
    saml_acs_url: zod.string().max(domainsVerifyCreateBodySamlAcsUrlMax).nullish(),
    saml_x509_cert: zod.string().nullish(),
    scim_enabled: zod.boolean().optional(),
})

export const invitesListResponseResultsItemTargetEmailMax = 254

export const invitesListResponseResultsItemFirstNameMax = 30

export const invitesListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const invitesListResponseResultsItemCreatedByOneFirstNameMax = 150

export const invitesListResponseResultsItemCreatedByOneLastNameMax = 150

export const invitesListResponseResultsItemCreatedByOneEmailMax = 254

export const invitesListResponseResultsItemSendEmailDefault = true
export const invitesListResponseResultsItemCombinePendingInvitesDefault = false

export const InvitesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            target_email: zod.email().max(invitesListResponseResultsItemTargetEmailMax),
            first_name: zod.string().max(invitesListResponseResultsItemFirstNameMax).optional(),
            emailing_attempt_made: zod.boolean(),
            level: zod
                .union([zod.literal(1), zod.literal(8), zod.literal(15)])
                .describe('* `1` - member\n* `8` - administrator\n* `15` - owner')
                .optional(),
            is_expired: zod.boolean().describe('Check if invite is older than INVITE_DAYS_VALIDITY days.'),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(invitesListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(invitesListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(invitesListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(invitesListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
            message: zod.string().nullish(),
            private_project_access: zod
                .unknown()
                .nullish()
                .describe('List of team IDs and corresponding access levels to private projects.'),
            send_email: zod.boolean().default(invitesListResponseResultsItemSendEmailDefault),
            combine_pending_invites: zod.boolean().default(invitesListResponseResultsItemCombinePendingInvitesDefault),
        })
    ),
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
        .describe('* `1` - member\n* `8` - administrator\n* `15` - owner')
        .optional(),
    message: zod.string().nullish(),
    private_project_access: zod
        .unknown()
        .nullish()
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
        .describe('* `1` - member\n* `8` - administrator\n* `15` - owner')
        .optional(),
    message: zod.string().nullish(),
    private_project_access: zod
        .unknown()
        .nullish()
        .describe('List of team IDs and corresponding access levels to private projects.'),
    send_email: zod.boolean().default(invitesBulkCreateBodySendEmailDefault),
    combine_pending_invites: zod.boolean().default(invitesBulkCreateBodyCombinePendingInvitesDefault),
})

/**
 * ViewSet for listing OAuth applications at the organization level (read-only).
 */
export const oauthApplicationsListResponseResultsItemNameMax = 255

export const oauthApplicationsListResponseResultsItemClientIdMax = 100

export const OauthApplicationsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid(),
                name: zod.string().max(oauthApplicationsListResponseResultsItemNameMax).optional(),
                client_id: zod.string().max(oauthApplicationsListResponseResultsItemClientIdMax).optional(),
                redirect_uris_list: zod.array(zod.string()),
                is_verified: zod.boolean().optional().describe('True if this application has been verified by PostHog'),
                created: zod.iso.datetime({}),
                updated: zod.iso.datetime({}),
            })
            .describe('Serializer for organization-scoped OAuth applications (read-only).')
    ),
})

/**
 * Projects for the current organization.
 */
export const List2Response = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.number(),
                uuid: zod.uuid(),
                organization: zod.uuid(),
                api_token: zod.string(),
                name: zod.string(),
                completed_snippet_onboarding: zod.boolean(),
                has_completed_onboarding_for: zod.unknown().nullable(),
                ingested_event: zod.boolean(),
                is_demo: zod.boolean(),
                timezone: zod.string(),
                access_control: zod.boolean(),
            })
            .describe(
                'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
            )
    ),
})

/**
 * Projects for the current organization.
 */
export const create2BodyNameMax = 200

export const create2BodyProductDescriptionMax = 1000

export const create2BodyAppUrlsItemMax = 200

export const create2BodySlackIncomingWebhookMax = 500

export const create2BodyPersonDisplayNamePropertiesItemMax = 400

export const create2BodySessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const create2BodySessionRecordingMinimumDurationMillisecondsMin = 0
export const create2BodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const create2BodySessionRecordingTriggerMatchTypeConfigMax = 24

export const create2BodyRecordingDomainsItemMax = 200

export const Create2Body = /* @__PURE__ */ zod
    .object({
        name: zod.string().min(1).max(create2BodyNameMax).optional(),
        product_description: zod.string().max(create2BodyProductDescriptionMax).nullish(),
        app_urls: zod.array(zod.string().max(create2BodyAppUrlsItemMax).nullable()).optional(),
        slack_incoming_webhook: zod.string().max(create2BodySlackIncomingWebhookMax).nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(create2BodyPersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod.string().regex(create2BodySessionRecordingSampleRateRegExp).nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(create2BodySessionRecordingMinimumDurationMillisecondsMin)
            .max(create2BodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(create2BodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod.array(zod.string().max(create2BodyRecordingDomainsItemMax).nullable()).nullish(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        flags_persistence_default: zod.boolean().nullish(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const retrieve2ResponseNameMax = 200

export const retrieve2ResponseProductDescriptionMax = 1000

export const retrieve2ResponseAppUrlsItemMax = 200

export const retrieve2ResponseSlackIncomingWebhookMax = 500

export const retrieve2ResponsePersonDisplayNamePropertiesItemMax = 400

export const retrieve2ResponseSessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const retrieve2ResponseSessionRecordingMinimumDurationMillisecondsMin = 0
export const retrieve2ResponseSessionRecordingMinimumDurationMillisecondsMax = 30000

export const retrieve2ResponseSessionRecordingTriggerMatchTypeConfigMax = 24

export const retrieve2ResponseRecordingDomainsItemMax = 200

export const Retrieve2Response = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        organization: zod.uuid(),
        name: zod.string().min(1).max(retrieve2ResponseNameMax).optional(),
        product_description: zod.string().max(retrieve2ResponseProductDescriptionMax).nullish(),
        created_at: zod.iso.datetime({}),
        effective_membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        has_group_types: zod.boolean(),
        group_types: zod.array(zod.record(zod.string(), zod.unknown())),
        live_events_token: zod.string().nullable(),
        updated_at: zod.iso.datetime({}),
        uuid: zod.uuid(),
        api_token: zod.string(),
        app_urls: zod.array(zod.string().max(retrieve2ResponseAppUrlsItemMax).nullable()).optional(),
        slack_incoming_webhook: zod.string().max(retrieve2ResponseSlackIncomingWebhookMax).nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        ingested_event: zod.boolean(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(retrieve2ResponsePersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod.string().regex(retrieve2ResponseSessionRecordingSampleRateRegExp).nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(retrieve2ResponseSessionRecordingMinimumDurationMillisecondsMin)
            .max(retrieve2ResponseSessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(retrieve2ResponseSessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod.array(zod.string().max(retrieve2ResponseRecordingDomainsItemMax).nullable()).nullish(),
        person_on_events_querying_enabled: zod.string(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        default_modifiers: zod.string(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        product_intents: zod.array(
            zod.object({
                product_type: zod.string().optional(),
                created_at: zod.iso.datetime({}).optional(),
                onboarding_completed_at: zod.iso.datetime({}).nullish(),
                updated_at: zod.iso.datetime({}).optional(),
            })
        ),
        flags_persistence_default: zod.boolean().nullish(),
        secret_api_token: zod.string().nullable(),
        secret_api_token_backup: zod.string().nullable(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        available_setup_task_ids: zod.array(
            zod
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
                    'enable_revenue_analytics_viewset',
                    'connect_revenue_source',
                    'set_up_revenue_goal',
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
                ])
                .describe(
                    '* `ingest_first_event` - ingest_first_event\n* `set_up_reverse_proxy` - set_up_reverse_proxy\n* `create_first_insight` - create_first_insight\n* `create_first_dashboard` - create_first_dashboard\n* `track_custom_events` - track_custom_events\n* `define_actions` - define_actions\n* `set_up_cohorts` - set_up_cohorts\n* `explore_trends_insight` - explore_trends_insight\n* `create_funnel` - create_funnel\n* `explore_retention_insight` - explore_retention_insight\n* `explore_paths_insight` - explore_paths_insight\n* `explore_stickiness_insight` - explore_stickiness_insight\n* `explore_lifecycle_insight` - explore_lifecycle_insight\n* `add_authorized_domain` - add_authorized_domain\n* `set_up_web_vitals` - set_up_web_vitals\n* `review_web_analytics_dashboard` - review_web_analytics_dashboard\n* `filter_web_analytics` - filter_web_analytics\n* `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals\n* `visit_web_vitals_dashboard` - visit_web_vitals_dashboard\n* `setup_session_recordings` - setup_session_recordings\n* `watch_session_recording` - watch_session_recording\n* `configure_recording_settings` - configure_recording_settings\n* `create_recording_playlist` - create_recording_playlist\n* `enable_console_logs` - enable_console_logs\n* `create_feature_flag` - create_feature_flag\n* `implement_flag_in_code` - implement_flag_in_code\n* `update_feature_flag_release_conditions` - update_feature_flag_release_conditions\n* `create_multivariate_flag` - create_multivariate_flag\n* `set_up_flag_payloads` - set_up_flag_payloads\n* `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes\n* `create_experiment` - create_experiment\n* `implement_experiment_variants` - implement_experiment_variants\n* `launch_experiment` - launch_experiment\n* `review_experiment_results` - review_experiment_results\n* `create_survey` - create_survey\n* `launch_survey` - launch_survey\n* `collect_survey_responses` - collect_survey_responses\n* `connect_source` - connect_source\n* `run_first_query` - run_first_query\n* `join_external_data` - join_external_data\n* `create_saved_view` - create_saved_view\n* `enable_error_tracking` - enable_error_tracking\n* `upload_source_maps` - upload_source_maps\n* `view_first_error` - view_first_error\n* `resolve_first_error` - resolve_first_error\n* `ingest_first_llm_event` - ingest_first_llm_event\n* `view_first_trace` - view_first_trace\n* `track_costs` - track_costs\n* `set_up_llm_evaluation` - set_up_llm_evaluation\n* `run_ai_playground` - run_ai_playground\n* `enable_revenue_analytics_viewset` - enable_revenue_analytics_viewset\n* `connect_revenue_source` - connect_revenue_source\n* `set_up_revenue_goal` - set_up_revenue_goal\n* `enable_log_capture` - enable_log_capture\n* `view_first_logs` - view_first_logs\n* `create_first_workflow` - create_first_workflow\n* `set_up_first_workflow_channel` - set_up_first_workflow_channel\n* `configure_workflow_trigger` - configure_workflow_trigger\n* `add_workflow_action` - add_workflow_action\n* `launch_workflow` - launch_workflow\n* `create_first_endpoint` - create_first_endpoint\n* `configure_endpoint` - configure_endpoint\n* `test_endpoint` - test_endpoint\n* `create_early_access_feature` - create_early_access_feature\n* `update_feature_stage` - update_feature_stage'
                )
        ),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const update2BodyNameMax = 200

export const update2BodyProductDescriptionMax = 1000

export const update2BodyAppUrlsItemMax = 200

export const update2BodySlackIncomingWebhookMax = 500

export const update2BodyPersonDisplayNamePropertiesItemMax = 400

export const update2BodySessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const update2BodySessionRecordingMinimumDurationMillisecondsMin = 0
export const update2BodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const update2BodySessionRecordingTriggerMatchTypeConfigMax = 24

export const update2BodyRecordingDomainsItemMax = 200

export const Update2Body = /* @__PURE__ */ zod
    .object({
        name: zod.string().min(1).max(update2BodyNameMax).optional(),
        product_description: zod.string().max(update2BodyProductDescriptionMax).nullish(),
        app_urls: zod.array(zod.string().max(update2BodyAppUrlsItemMax).nullable()).optional(),
        slack_incoming_webhook: zod.string().max(update2BodySlackIncomingWebhookMax).nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(update2BodyPersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod.string().regex(update2BodySessionRecordingSampleRateRegExp).nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(update2BodySessionRecordingMinimumDurationMillisecondsMin)
            .max(update2BodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(update2BodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod.array(zod.string().max(update2BodyRecordingDomainsItemMax).nullable()).nullish(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        flags_persistence_default: zod.boolean().nullish(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

export const update2ResponseNameMax = 200

export const update2ResponseProductDescriptionMax = 1000

export const update2ResponseAppUrlsItemMax = 200

export const update2ResponseSlackIncomingWebhookMax = 500

export const update2ResponsePersonDisplayNamePropertiesItemMax = 400

export const update2ResponseSessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const update2ResponseSessionRecordingMinimumDurationMillisecondsMin = 0
export const update2ResponseSessionRecordingMinimumDurationMillisecondsMax = 30000

export const update2ResponseSessionRecordingTriggerMatchTypeConfigMax = 24

export const update2ResponseRecordingDomainsItemMax = 200

export const Update2Response = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        organization: zod.uuid(),
        name: zod.string().min(1).max(update2ResponseNameMax).optional(),
        product_description: zod.string().max(update2ResponseProductDescriptionMax).nullish(),
        created_at: zod.iso.datetime({}),
        effective_membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        has_group_types: zod.boolean(),
        group_types: zod.array(zod.record(zod.string(), zod.unknown())),
        live_events_token: zod.string().nullable(),
        updated_at: zod.iso.datetime({}),
        uuid: zod.uuid(),
        api_token: zod.string(),
        app_urls: zod.array(zod.string().max(update2ResponseAppUrlsItemMax).nullable()).optional(),
        slack_incoming_webhook: zod.string().max(update2ResponseSlackIncomingWebhookMax).nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        ingested_event: zod.boolean(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(update2ResponsePersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod.string().regex(update2ResponseSessionRecordingSampleRateRegExp).nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(update2ResponseSessionRecordingMinimumDurationMillisecondsMin)
            .max(update2ResponseSessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(update2ResponseSessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod.array(zod.string().max(update2ResponseRecordingDomainsItemMax).nullable()).nullish(),
        person_on_events_querying_enabled: zod.string(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        default_modifiers: zod.string(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        product_intents: zod.array(
            zod.object({
                product_type: zod.string().optional(),
                created_at: zod.iso.datetime({}).optional(),
                onboarding_completed_at: zod.iso.datetime({}).nullish(),
                updated_at: zod.iso.datetime({}).optional(),
            })
        ),
        flags_persistence_default: zod.boolean().nullish(),
        secret_api_token: zod.string().nullable(),
        secret_api_token_backup: zod.string().nullable(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        available_setup_task_ids: zod.array(
            zod
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
                    'enable_revenue_analytics_viewset',
                    'connect_revenue_source',
                    'set_up_revenue_goal',
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
                ])
                .describe(
                    '* `ingest_first_event` - ingest_first_event\n* `set_up_reverse_proxy` - set_up_reverse_proxy\n* `create_first_insight` - create_first_insight\n* `create_first_dashboard` - create_first_dashboard\n* `track_custom_events` - track_custom_events\n* `define_actions` - define_actions\n* `set_up_cohorts` - set_up_cohorts\n* `explore_trends_insight` - explore_trends_insight\n* `create_funnel` - create_funnel\n* `explore_retention_insight` - explore_retention_insight\n* `explore_paths_insight` - explore_paths_insight\n* `explore_stickiness_insight` - explore_stickiness_insight\n* `explore_lifecycle_insight` - explore_lifecycle_insight\n* `add_authorized_domain` - add_authorized_domain\n* `set_up_web_vitals` - set_up_web_vitals\n* `review_web_analytics_dashboard` - review_web_analytics_dashboard\n* `filter_web_analytics` - filter_web_analytics\n* `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals\n* `visit_web_vitals_dashboard` - visit_web_vitals_dashboard\n* `setup_session_recordings` - setup_session_recordings\n* `watch_session_recording` - watch_session_recording\n* `configure_recording_settings` - configure_recording_settings\n* `create_recording_playlist` - create_recording_playlist\n* `enable_console_logs` - enable_console_logs\n* `create_feature_flag` - create_feature_flag\n* `implement_flag_in_code` - implement_flag_in_code\n* `update_feature_flag_release_conditions` - update_feature_flag_release_conditions\n* `create_multivariate_flag` - create_multivariate_flag\n* `set_up_flag_payloads` - set_up_flag_payloads\n* `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes\n* `create_experiment` - create_experiment\n* `implement_experiment_variants` - implement_experiment_variants\n* `launch_experiment` - launch_experiment\n* `review_experiment_results` - review_experiment_results\n* `create_survey` - create_survey\n* `launch_survey` - launch_survey\n* `collect_survey_responses` - collect_survey_responses\n* `connect_source` - connect_source\n* `run_first_query` - run_first_query\n* `join_external_data` - join_external_data\n* `create_saved_view` - create_saved_view\n* `enable_error_tracking` - enable_error_tracking\n* `upload_source_maps` - upload_source_maps\n* `view_first_error` - view_first_error\n* `resolve_first_error` - resolve_first_error\n* `ingest_first_llm_event` - ingest_first_llm_event\n* `view_first_trace` - view_first_trace\n* `track_costs` - track_costs\n* `set_up_llm_evaluation` - set_up_llm_evaluation\n* `run_ai_playground` - run_ai_playground\n* `enable_revenue_analytics_viewset` - enable_revenue_analytics_viewset\n* `connect_revenue_source` - connect_revenue_source\n* `set_up_revenue_goal` - set_up_revenue_goal\n* `enable_log_capture` - enable_log_capture\n* `view_first_logs` - view_first_logs\n* `create_first_workflow` - create_first_workflow\n* `set_up_first_workflow_channel` - set_up_first_workflow_channel\n* `configure_workflow_trigger` - configure_workflow_trigger\n* `add_workflow_action` - add_workflow_action\n* `launch_workflow` - launch_workflow\n* `create_first_endpoint` - create_first_endpoint\n* `configure_endpoint` - configure_endpoint\n* `test_endpoint` - test_endpoint\n* `create_early_access_feature` - create_early_access_feature\n* `update_feature_stage` - update_feature_stage'
                )
        ),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const partialUpdate2BodyNameMax = 200

export const partialUpdate2BodyProductDescriptionMax = 1000

export const partialUpdate2BodyAppUrlsItemMax = 200

export const partialUpdate2BodySlackIncomingWebhookMax = 500

export const partialUpdate2BodyPersonDisplayNamePropertiesItemMax = 400

export const partialUpdate2BodySessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const partialUpdate2BodySessionRecordingMinimumDurationMillisecondsMin = 0
export const partialUpdate2BodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const partialUpdate2BodySessionRecordingTriggerMatchTypeConfigMax = 24

export const partialUpdate2BodyRecordingDomainsItemMax = 200

export const PartialUpdate2Body = /* @__PURE__ */ zod
    .object({
        name: zod.string().min(1).max(partialUpdate2BodyNameMax).optional(),
        product_description: zod.string().max(partialUpdate2BodyProductDescriptionMax).nullish(),
        app_urls: zod.array(zod.string().max(partialUpdate2BodyAppUrlsItemMax).nullable()).optional(),
        slack_incoming_webhook: zod.string().max(partialUpdate2BodySlackIncomingWebhookMax).nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(partialUpdate2BodyPersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod.string().regex(partialUpdate2BodySessionRecordingSampleRateRegExp).nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(partialUpdate2BodySessionRecordingMinimumDurationMillisecondsMin)
            .max(partialUpdate2BodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(partialUpdate2BodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod.array(zod.string().max(partialUpdate2BodyRecordingDomainsItemMax).nullable()).nullish(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        flags_persistence_default: zod.boolean().nullish(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

export const partialUpdate2ResponseNameMax = 200

export const partialUpdate2ResponseProductDescriptionMax = 1000

export const partialUpdate2ResponseAppUrlsItemMax = 200

export const partialUpdate2ResponseSlackIncomingWebhookMax = 500

export const partialUpdate2ResponsePersonDisplayNamePropertiesItemMax = 400

export const partialUpdate2ResponseSessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const partialUpdate2ResponseSessionRecordingMinimumDurationMillisecondsMin = 0
export const partialUpdate2ResponseSessionRecordingMinimumDurationMillisecondsMax = 30000

export const partialUpdate2ResponseSessionRecordingTriggerMatchTypeConfigMax = 24

export const partialUpdate2ResponseRecordingDomainsItemMax = 200

export const PartialUpdate2Response = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        organization: zod.uuid(),
        name: zod.string().min(1).max(partialUpdate2ResponseNameMax).optional(),
        product_description: zod.string().max(partialUpdate2ResponseProductDescriptionMax).nullish(),
        created_at: zod.iso.datetime({}),
        effective_membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        has_group_types: zod.boolean(),
        group_types: zod.array(zod.record(zod.string(), zod.unknown())),
        live_events_token: zod.string().nullable(),
        updated_at: zod.iso.datetime({}),
        uuid: zod.uuid(),
        api_token: zod.string(),
        app_urls: zod.array(zod.string().max(partialUpdate2ResponseAppUrlsItemMax).nullable()).optional(),
        slack_incoming_webhook: zod.string().max(partialUpdate2ResponseSlackIncomingWebhookMax).nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        ingested_event: zod.boolean(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(partialUpdate2ResponsePersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(partialUpdate2ResponseSessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(partialUpdate2ResponseSessionRecordingMinimumDurationMillisecondsMin)
            .max(partialUpdate2ResponseSessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(partialUpdate2ResponseSessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(partialUpdate2ResponseRecordingDomainsItemMax).nullable())
            .nullish(),
        person_on_events_querying_enabled: zod.string(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        default_modifiers: zod.string(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        product_intents: zod.array(
            zod.object({
                product_type: zod.string().optional(),
                created_at: zod.iso.datetime({}).optional(),
                onboarding_completed_at: zod.iso.datetime({}).nullish(),
                updated_at: zod.iso.datetime({}).optional(),
            })
        ),
        flags_persistence_default: zod.boolean().nullish(),
        secret_api_token: zod.string().nullable(),
        secret_api_token_backup: zod.string().nullable(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        available_setup_task_ids: zod.array(
            zod
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
                    'enable_revenue_analytics_viewset',
                    'connect_revenue_source',
                    'set_up_revenue_goal',
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
                ])
                .describe(
                    '* `ingest_first_event` - ingest_first_event\n* `set_up_reverse_proxy` - set_up_reverse_proxy\n* `create_first_insight` - create_first_insight\n* `create_first_dashboard` - create_first_dashboard\n* `track_custom_events` - track_custom_events\n* `define_actions` - define_actions\n* `set_up_cohorts` - set_up_cohorts\n* `explore_trends_insight` - explore_trends_insight\n* `create_funnel` - create_funnel\n* `explore_retention_insight` - explore_retention_insight\n* `explore_paths_insight` - explore_paths_insight\n* `explore_stickiness_insight` - explore_stickiness_insight\n* `explore_lifecycle_insight` - explore_lifecycle_insight\n* `add_authorized_domain` - add_authorized_domain\n* `set_up_web_vitals` - set_up_web_vitals\n* `review_web_analytics_dashboard` - review_web_analytics_dashboard\n* `filter_web_analytics` - filter_web_analytics\n* `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals\n* `visit_web_vitals_dashboard` - visit_web_vitals_dashboard\n* `setup_session_recordings` - setup_session_recordings\n* `watch_session_recording` - watch_session_recording\n* `configure_recording_settings` - configure_recording_settings\n* `create_recording_playlist` - create_recording_playlist\n* `enable_console_logs` - enable_console_logs\n* `create_feature_flag` - create_feature_flag\n* `implement_flag_in_code` - implement_flag_in_code\n* `update_feature_flag_release_conditions` - update_feature_flag_release_conditions\n* `create_multivariate_flag` - create_multivariate_flag\n* `set_up_flag_payloads` - set_up_flag_payloads\n* `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes\n* `create_experiment` - create_experiment\n* `implement_experiment_variants` - implement_experiment_variants\n* `launch_experiment` - launch_experiment\n* `review_experiment_results` - review_experiment_results\n* `create_survey` - create_survey\n* `launch_survey` - launch_survey\n* `collect_survey_responses` - collect_survey_responses\n* `connect_source` - connect_source\n* `run_first_query` - run_first_query\n* `join_external_data` - join_external_data\n* `create_saved_view` - create_saved_view\n* `enable_error_tracking` - enable_error_tracking\n* `upload_source_maps` - upload_source_maps\n* `view_first_error` - view_first_error\n* `resolve_first_error` - resolve_first_error\n* `ingest_first_llm_event` - ingest_first_llm_event\n* `view_first_trace` - view_first_trace\n* `track_costs` - track_costs\n* `set_up_llm_evaluation` - set_up_llm_evaluation\n* `run_ai_playground` - run_ai_playground\n* `enable_revenue_analytics_viewset` - enable_revenue_analytics_viewset\n* `connect_revenue_source` - connect_revenue_source\n* `set_up_revenue_goal` - set_up_revenue_goal\n* `enable_log_capture` - enable_log_capture\n* `view_first_logs` - view_first_logs\n* `create_first_workflow` - create_first_workflow\n* `set_up_first_workflow_channel` - set_up_first_workflow_channel\n* `configure_workflow_trigger` - configure_workflow_trigger\n* `add_workflow_action` - add_workflow_action\n* `launch_workflow` - launch_workflow\n* `create_first_endpoint` - create_first_endpoint\n* `configure_endpoint` - configure_endpoint\n* `test_endpoint` - test_endpoint\n* `create_early_access_feature` - create_early_access_feature\n* `update_feature_stage` - update_feature_stage'
                )
        ),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const activityRetrieveResponseNameMax = 200

export const activityRetrieveResponseProductDescriptionMax = 1000

export const activityRetrieveResponseAppUrlsItemMax = 200

export const activityRetrieveResponseSlackIncomingWebhookMax = 500

export const activityRetrieveResponsePersonDisplayNamePropertiesItemMax = 400

export const activityRetrieveResponseSessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const activityRetrieveResponseSessionRecordingMinimumDurationMillisecondsMin = 0
export const activityRetrieveResponseSessionRecordingMinimumDurationMillisecondsMax = 30000

export const activityRetrieveResponseSessionRecordingTriggerMatchTypeConfigMax = 24

export const activityRetrieveResponseRecordingDomainsItemMax = 200

export const ActivityRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        organization: zod.uuid(),
        name: zod.string().min(1).max(activityRetrieveResponseNameMax).optional(),
        product_description: zod.string().max(activityRetrieveResponseProductDescriptionMax).nullish(),
        created_at: zod.iso.datetime({}),
        effective_membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        has_group_types: zod.boolean(),
        group_types: zod.array(zod.record(zod.string(), zod.unknown())),
        live_events_token: zod.string().nullable(),
        updated_at: zod.iso.datetime({}),
        uuid: zod.uuid(),
        api_token: zod.string(),
        app_urls: zod.array(zod.string().max(activityRetrieveResponseAppUrlsItemMax).nullable()).optional(),
        slack_incoming_webhook: zod.string().max(activityRetrieveResponseSlackIncomingWebhookMax).nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        ingested_event: zod.boolean(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(activityRetrieveResponsePersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(activityRetrieveResponseSessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(activityRetrieveResponseSessionRecordingMinimumDurationMillisecondsMin)
            .max(activityRetrieveResponseSessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(activityRetrieveResponseSessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(activityRetrieveResponseRecordingDomainsItemMax).nullable())
            .nullish(),
        person_on_events_querying_enabled: zod.string(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        default_modifiers: zod.string(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        product_intents: zod.array(
            zod.object({
                product_type: zod.string().optional(),
                created_at: zod.iso.datetime({}).optional(),
                onboarding_completed_at: zod.iso.datetime({}).nullish(),
                updated_at: zod.iso.datetime({}).optional(),
            })
        ),
        flags_persistence_default: zod.boolean().nullish(),
        secret_api_token: zod.string().nullable(),
        secret_api_token_backup: zod.string().nullable(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        available_setup_task_ids: zod.array(
            zod
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
                    'enable_revenue_analytics_viewset',
                    'connect_revenue_source',
                    'set_up_revenue_goal',
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
                ])
                .describe(
                    '* `ingest_first_event` - ingest_first_event\n* `set_up_reverse_proxy` - set_up_reverse_proxy\n* `create_first_insight` - create_first_insight\n* `create_first_dashboard` - create_first_dashboard\n* `track_custom_events` - track_custom_events\n* `define_actions` - define_actions\n* `set_up_cohorts` - set_up_cohorts\n* `explore_trends_insight` - explore_trends_insight\n* `create_funnel` - create_funnel\n* `explore_retention_insight` - explore_retention_insight\n* `explore_paths_insight` - explore_paths_insight\n* `explore_stickiness_insight` - explore_stickiness_insight\n* `explore_lifecycle_insight` - explore_lifecycle_insight\n* `add_authorized_domain` - add_authorized_domain\n* `set_up_web_vitals` - set_up_web_vitals\n* `review_web_analytics_dashboard` - review_web_analytics_dashboard\n* `filter_web_analytics` - filter_web_analytics\n* `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals\n* `visit_web_vitals_dashboard` - visit_web_vitals_dashboard\n* `setup_session_recordings` - setup_session_recordings\n* `watch_session_recording` - watch_session_recording\n* `configure_recording_settings` - configure_recording_settings\n* `create_recording_playlist` - create_recording_playlist\n* `enable_console_logs` - enable_console_logs\n* `create_feature_flag` - create_feature_flag\n* `implement_flag_in_code` - implement_flag_in_code\n* `update_feature_flag_release_conditions` - update_feature_flag_release_conditions\n* `create_multivariate_flag` - create_multivariate_flag\n* `set_up_flag_payloads` - set_up_flag_payloads\n* `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes\n* `create_experiment` - create_experiment\n* `implement_experiment_variants` - implement_experiment_variants\n* `launch_experiment` - launch_experiment\n* `review_experiment_results` - review_experiment_results\n* `create_survey` - create_survey\n* `launch_survey` - launch_survey\n* `collect_survey_responses` - collect_survey_responses\n* `connect_source` - connect_source\n* `run_first_query` - run_first_query\n* `join_external_data` - join_external_data\n* `create_saved_view` - create_saved_view\n* `enable_error_tracking` - enable_error_tracking\n* `upload_source_maps` - upload_source_maps\n* `view_first_error` - view_first_error\n* `resolve_first_error` - resolve_first_error\n* `ingest_first_llm_event` - ingest_first_llm_event\n* `view_first_trace` - view_first_trace\n* `track_costs` - track_costs\n* `set_up_llm_evaluation` - set_up_llm_evaluation\n* `run_ai_playground` - run_ai_playground\n* `enable_revenue_analytics_viewset` - enable_revenue_analytics_viewset\n* `connect_revenue_source` - connect_revenue_source\n* `set_up_revenue_goal` - set_up_revenue_goal\n* `enable_log_capture` - enable_log_capture\n* `view_first_logs` - view_first_logs\n* `create_first_workflow` - create_first_workflow\n* `set_up_first_workflow_channel` - set_up_first_workflow_channel\n* `configure_workflow_trigger` - configure_workflow_trigger\n* `add_workflow_action` - add_workflow_action\n* `launch_workflow` - launch_workflow\n* `create_first_endpoint` - create_first_endpoint\n* `configure_endpoint` - configure_endpoint\n* `test_endpoint` - test_endpoint\n* `create_early_access_feature` - create_early_access_feature\n* `update_feature_stage` - update_feature_stage'
                )
        ),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const addProductIntentPartialUpdateBodyNameMax = 200

export const addProductIntentPartialUpdateBodyProductDescriptionMax = 1000

export const addProductIntentPartialUpdateBodyAppUrlsItemMax = 200

export const addProductIntentPartialUpdateBodySlackIncomingWebhookMax = 500

export const addProductIntentPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const addProductIntentPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const addProductIntentPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const addProductIntentPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const addProductIntentPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const addProductIntentPartialUpdateBodyRecordingDomainsItemMax = 200

export const AddProductIntentPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().min(1).max(addProductIntentPartialUpdateBodyNameMax).optional(),
        product_description: zod.string().max(addProductIntentPartialUpdateBodyProductDescriptionMax).nullish(),
        app_urls: zod.array(zod.string().max(addProductIntentPartialUpdateBodyAppUrlsItemMax).nullable()).optional(),
        slack_incoming_webhook: zod.string().max(addProductIntentPartialUpdateBodySlackIncomingWebhookMax).nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(addProductIntentPartialUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(addProductIntentPartialUpdateBodySessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(addProductIntentPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(addProductIntentPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(addProductIntentPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(addProductIntentPartialUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        flags_persistence_default: zod.boolean().nullish(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

export const addProductIntentPartialUpdateResponseNameMax = 200

export const addProductIntentPartialUpdateResponseProductDescriptionMax = 1000

export const addProductIntentPartialUpdateResponseAppUrlsItemMax = 200

export const addProductIntentPartialUpdateResponseSlackIncomingWebhookMax = 500

export const addProductIntentPartialUpdateResponsePersonDisplayNamePropertiesItemMax = 400

export const addProductIntentPartialUpdateResponseSessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const addProductIntentPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMin = 0
export const addProductIntentPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMax = 30000

export const addProductIntentPartialUpdateResponseSessionRecordingTriggerMatchTypeConfigMax = 24

export const addProductIntentPartialUpdateResponseRecordingDomainsItemMax = 200

export const AddProductIntentPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        organization: zod.uuid(),
        name: zod.string().min(1).max(addProductIntentPartialUpdateResponseNameMax).optional(),
        product_description: zod.string().max(addProductIntentPartialUpdateResponseProductDescriptionMax).nullish(),
        created_at: zod.iso.datetime({}),
        effective_membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        has_group_types: zod.boolean(),
        group_types: zod.array(zod.record(zod.string(), zod.unknown())),
        live_events_token: zod.string().nullable(),
        updated_at: zod.iso.datetime({}),
        uuid: zod.uuid(),
        api_token: zod.string(),
        app_urls: zod
            .array(zod.string().max(addProductIntentPartialUpdateResponseAppUrlsItemMax).nullable())
            .optional(),
        slack_incoming_webhook: zod
            .string()
            .max(addProductIntentPartialUpdateResponseSlackIncomingWebhookMax)
            .nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        ingested_event: zod.boolean(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(addProductIntentPartialUpdateResponsePersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(addProductIntentPartialUpdateResponseSessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(addProductIntentPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMin)
            .max(addProductIntentPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(addProductIntentPartialUpdateResponseSessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(addProductIntentPartialUpdateResponseRecordingDomainsItemMax).nullable())
            .nullish(),
        person_on_events_querying_enabled: zod.string(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        default_modifiers: zod.string(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        product_intents: zod.array(
            zod.object({
                product_type: zod.string().optional(),
                created_at: zod.iso.datetime({}).optional(),
                onboarding_completed_at: zod.iso.datetime({}).nullish(),
                updated_at: zod.iso.datetime({}).optional(),
            })
        ),
        flags_persistence_default: zod.boolean().nullish(),
        secret_api_token: zod.string().nullable(),
        secret_api_token_backup: zod.string().nullable(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        available_setup_task_ids: zod.array(
            zod
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
                    'enable_revenue_analytics_viewset',
                    'connect_revenue_source',
                    'set_up_revenue_goal',
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
                ])
                .describe(
                    '* `ingest_first_event` - ingest_first_event\n* `set_up_reverse_proxy` - set_up_reverse_proxy\n* `create_first_insight` - create_first_insight\n* `create_first_dashboard` - create_first_dashboard\n* `track_custom_events` - track_custom_events\n* `define_actions` - define_actions\n* `set_up_cohorts` - set_up_cohorts\n* `explore_trends_insight` - explore_trends_insight\n* `create_funnel` - create_funnel\n* `explore_retention_insight` - explore_retention_insight\n* `explore_paths_insight` - explore_paths_insight\n* `explore_stickiness_insight` - explore_stickiness_insight\n* `explore_lifecycle_insight` - explore_lifecycle_insight\n* `add_authorized_domain` - add_authorized_domain\n* `set_up_web_vitals` - set_up_web_vitals\n* `review_web_analytics_dashboard` - review_web_analytics_dashboard\n* `filter_web_analytics` - filter_web_analytics\n* `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals\n* `visit_web_vitals_dashboard` - visit_web_vitals_dashboard\n* `setup_session_recordings` - setup_session_recordings\n* `watch_session_recording` - watch_session_recording\n* `configure_recording_settings` - configure_recording_settings\n* `create_recording_playlist` - create_recording_playlist\n* `enable_console_logs` - enable_console_logs\n* `create_feature_flag` - create_feature_flag\n* `implement_flag_in_code` - implement_flag_in_code\n* `update_feature_flag_release_conditions` - update_feature_flag_release_conditions\n* `create_multivariate_flag` - create_multivariate_flag\n* `set_up_flag_payloads` - set_up_flag_payloads\n* `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes\n* `create_experiment` - create_experiment\n* `implement_experiment_variants` - implement_experiment_variants\n* `launch_experiment` - launch_experiment\n* `review_experiment_results` - review_experiment_results\n* `create_survey` - create_survey\n* `launch_survey` - launch_survey\n* `collect_survey_responses` - collect_survey_responses\n* `connect_source` - connect_source\n* `run_first_query` - run_first_query\n* `join_external_data` - join_external_data\n* `create_saved_view` - create_saved_view\n* `enable_error_tracking` - enable_error_tracking\n* `upload_source_maps` - upload_source_maps\n* `view_first_error` - view_first_error\n* `resolve_first_error` - resolve_first_error\n* `ingest_first_llm_event` - ingest_first_llm_event\n* `view_first_trace` - view_first_trace\n* `track_costs` - track_costs\n* `set_up_llm_evaluation` - set_up_llm_evaluation\n* `run_ai_playground` - run_ai_playground\n* `enable_revenue_analytics_viewset` - enable_revenue_analytics_viewset\n* `connect_revenue_source` - connect_revenue_source\n* `set_up_revenue_goal` - set_up_revenue_goal\n* `enable_log_capture` - enable_log_capture\n* `view_first_logs` - view_first_logs\n* `create_first_workflow` - create_first_workflow\n* `set_up_first_workflow_channel` - set_up_first_workflow_channel\n* `configure_workflow_trigger` - configure_workflow_trigger\n* `add_workflow_action` - add_workflow_action\n* `launch_workflow` - launch_workflow\n* `create_first_endpoint` - create_first_endpoint\n* `configure_endpoint` - configure_endpoint\n* `test_endpoint` - test_endpoint\n* `create_early_access_feature` - create_early_access_feature\n* `update_feature_stage` - update_feature_stage'
                )
        ),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const changeOrganizationCreateBodyNameMax = 200

export const changeOrganizationCreateBodyProductDescriptionMax = 1000

export const changeOrganizationCreateBodyAppUrlsItemMax = 200

export const changeOrganizationCreateBodySlackIncomingWebhookMax = 500

export const changeOrganizationCreateBodyPersonDisplayNamePropertiesItemMax = 400

export const changeOrganizationCreateBodySessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const changeOrganizationCreateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const changeOrganizationCreateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const changeOrganizationCreateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const changeOrganizationCreateBodyRecordingDomainsItemMax = 200

export const ChangeOrganizationCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().min(1).max(changeOrganizationCreateBodyNameMax).optional(),
        product_description: zod.string().max(changeOrganizationCreateBodyProductDescriptionMax).nullish(),
        app_urls: zod.array(zod.string().max(changeOrganizationCreateBodyAppUrlsItemMax).nullable()).optional(),
        slack_incoming_webhook: zod.string().max(changeOrganizationCreateBodySlackIncomingWebhookMax).nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(changeOrganizationCreateBodyPersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(changeOrganizationCreateBodySessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(changeOrganizationCreateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(changeOrganizationCreateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(changeOrganizationCreateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(changeOrganizationCreateBodyRecordingDomainsItemMax).nullable())
            .nullish(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        flags_persistence_default: zod.boolean().nullish(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

export const changeOrganizationCreateResponseNameMax = 200

export const changeOrganizationCreateResponseProductDescriptionMax = 1000

export const changeOrganizationCreateResponseAppUrlsItemMax = 200

export const changeOrganizationCreateResponseSlackIncomingWebhookMax = 500

export const changeOrganizationCreateResponsePersonDisplayNamePropertiesItemMax = 400

export const changeOrganizationCreateResponseSessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const changeOrganizationCreateResponseSessionRecordingMinimumDurationMillisecondsMin = 0
export const changeOrganizationCreateResponseSessionRecordingMinimumDurationMillisecondsMax = 30000

export const changeOrganizationCreateResponseSessionRecordingTriggerMatchTypeConfigMax = 24

export const changeOrganizationCreateResponseRecordingDomainsItemMax = 200

export const ChangeOrganizationCreateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        organization: zod.uuid(),
        name: zod.string().min(1).max(changeOrganizationCreateResponseNameMax).optional(),
        product_description: zod.string().max(changeOrganizationCreateResponseProductDescriptionMax).nullish(),
        created_at: zod.iso.datetime({}),
        effective_membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        has_group_types: zod.boolean(),
        group_types: zod.array(zod.record(zod.string(), zod.unknown())),
        live_events_token: zod.string().nullable(),
        updated_at: zod.iso.datetime({}),
        uuid: zod.uuid(),
        api_token: zod.string(),
        app_urls: zod.array(zod.string().max(changeOrganizationCreateResponseAppUrlsItemMax).nullable()).optional(),
        slack_incoming_webhook: zod.string().max(changeOrganizationCreateResponseSlackIncomingWebhookMax).nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        ingested_event: zod.boolean(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(changeOrganizationCreateResponsePersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(changeOrganizationCreateResponseSessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(changeOrganizationCreateResponseSessionRecordingMinimumDurationMillisecondsMin)
            .max(changeOrganizationCreateResponseSessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(changeOrganizationCreateResponseSessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(changeOrganizationCreateResponseRecordingDomainsItemMax).nullable())
            .nullish(),
        person_on_events_querying_enabled: zod.string(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        default_modifiers: zod.string(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        product_intents: zod.array(
            zod.object({
                product_type: zod.string().optional(),
                created_at: zod.iso.datetime({}).optional(),
                onboarding_completed_at: zod.iso.datetime({}).nullish(),
                updated_at: zod.iso.datetime({}).optional(),
            })
        ),
        flags_persistence_default: zod.boolean().nullish(),
        secret_api_token: zod.string().nullable(),
        secret_api_token_backup: zod.string().nullable(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        available_setup_task_ids: zod.array(
            zod
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
                    'enable_revenue_analytics_viewset',
                    'connect_revenue_source',
                    'set_up_revenue_goal',
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
                ])
                .describe(
                    '* `ingest_first_event` - ingest_first_event\n* `set_up_reverse_proxy` - set_up_reverse_proxy\n* `create_first_insight` - create_first_insight\n* `create_first_dashboard` - create_first_dashboard\n* `track_custom_events` - track_custom_events\n* `define_actions` - define_actions\n* `set_up_cohorts` - set_up_cohorts\n* `explore_trends_insight` - explore_trends_insight\n* `create_funnel` - create_funnel\n* `explore_retention_insight` - explore_retention_insight\n* `explore_paths_insight` - explore_paths_insight\n* `explore_stickiness_insight` - explore_stickiness_insight\n* `explore_lifecycle_insight` - explore_lifecycle_insight\n* `add_authorized_domain` - add_authorized_domain\n* `set_up_web_vitals` - set_up_web_vitals\n* `review_web_analytics_dashboard` - review_web_analytics_dashboard\n* `filter_web_analytics` - filter_web_analytics\n* `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals\n* `visit_web_vitals_dashboard` - visit_web_vitals_dashboard\n* `setup_session_recordings` - setup_session_recordings\n* `watch_session_recording` - watch_session_recording\n* `configure_recording_settings` - configure_recording_settings\n* `create_recording_playlist` - create_recording_playlist\n* `enable_console_logs` - enable_console_logs\n* `create_feature_flag` - create_feature_flag\n* `implement_flag_in_code` - implement_flag_in_code\n* `update_feature_flag_release_conditions` - update_feature_flag_release_conditions\n* `create_multivariate_flag` - create_multivariate_flag\n* `set_up_flag_payloads` - set_up_flag_payloads\n* `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes\n* `create_experiment` - create_experiment\n* `implement_experiment_variants` - implement_experiment_variants\n* `launch_experiment` - launch_experiment\n* `review_experiment_results` - review_experiment_results\n* `create_survey` - create_survey\n* `launch_survey` - launch_survey\n* `collect_survey_responses` - collect_survey_responses\n* `connect_source` - connect_source\n* `run_first_query` - run_first_query\n* `join_external_data` - join_external_data\n* `create_saved_view` - create_saved_view\n* `enable_error_tracking` - enable_error_tracking\n* `upload_source_maps` - upload_source_maps\n* `view_first_error` - view_first_error\n* `resolve_first_error` - resolve_first_error\n* `ingest_first_llm_event` - ingest_first_llm_event\n* `view_first_trace` - view_first_trace\n* `track_costs` - track_costs\n* `set_up_llm_evaluation` - set_up_llm_evaluation\n* `run_ai_playground` - run_ai_playground\n* `enable_revenue_analytics_viewset` - enable_revenue_analytics_viewset\n* `connect_revenue_source` - connect_revenue_source\n* `set_up_revenue_goal` - set_up_revenue_goal\n* `enable_log_capture` - enable_log_capture\n* `view_first_logs` - view_first_logs\n* `create_first_workflow` - create_first_workflow\n* `set_up_first_workflow_channel` - set_up_first_workflow_channel\n* `configure_workflow_trigger` - configure_workflow_trigger\n* `add_workflow_action` - add_workflow_action\n* `launch_workflow` - launch_workflow\n* `create_first_endpoint` - create_first_endpoint\n* `configure_endpoint` - configure_endpoint\n* `test_endpoint` - test_endpoint\n* `create_early_access_feature` - create_early_access_feature\n* `update_feature_stage` - update_feature_stage'
                )
        ),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const completeProductOnboardingPartialUpdateBodyNameMax = 200

export const completeProductOnboardingPartialUpdateBodyProductDescriptionMax = 1000

export const completeProductOnboardingPartialUpdateBodyAppUrlsItemMax = 200

export const completeProductOnboardingPartialUpdateBodySlackIncomingWebhookMax = 500

export const completeProductOnboardingPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const completeProductOnboardingPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const completeProductOnboardingPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const completeProductOnboardingPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const completeProductOnboardingPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const completeProductOnboardingPartialUpdateBodyRecordingDomainsItemMax = 200

export const CompleteProductOnboardingPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().min(1).max(completeProductOnboardingPartialUpdateBodyNameMax).optional(),
        product_description: zod
            .string()
            .max(completeProductOnboardingPartialUpdateBodyProductDescriptionMax)
            .nullish(),
        app_urls: zod
            .array(zod.string().max(completeProductOnboardingPartialUpdateBodyAppUrlsItemMax).nullable())
            .optional(),
        slack_incoming_webhook: zod
            .string()
            .max(completeProductOnboardingPartialUpdateBodySlackIncomingWebhookMax)
            .nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(completeProductOnboardingPartialUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(completeProductOnboardingPartialUpdateBodySessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(completeProductOnboardingPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(completeProductOnboardingPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(completeProductOnboardingPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(completeProductOnboardingPartialUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        flags_persistence_default: zod.boolean().nullish(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

export const completeProductOnboardingPartialUpdateResponseNameMax = 200

export const completeProductOnboardingPartialUpdateResponseProductDescriptionMax = 1000

export const completeProductOnboardingPartialUpdateResponseAppUrlsItemMax = 200

export const completeProductOnboardingPartialUpdateResponseSlackIncomingWebhookMax = 500

export const completeProductOnboardingPartialUpdateResponsePersonDisplayNamePropertiesItemMax = 400

export const completeProductOnboardingPartialUpdateResponseSessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const completeProductOnboardingPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMin = 0
export const completeProductOnboardingPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMax = 30000

export const completeProductOnboardingPartialUpdateResponseSessionRecordingTriggerMatchTypeConfigMax = 24

export const completeProductOnboardingPartialUpdateResponseRecordingDomainsItemMax = 200

export const CompleteProductOnboardingPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        organization: zod.uuid(),
        name: zod.string().min(1).max(completeProductOnboardingPartialUpdateResponseNameMax).optional(),
        product_description: zod
            .string()
            .max(completeProductOnboardingPartialUpdateResponseProductDescriptionMax)
            .nullish(),
        created_at: zod.iso.datetime({}),
        effective_membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        has_group_types: zod.boolean(),
        group_types: zod.array(zod.record(zod.string(), zod.unknown())),
        live_events_token: zod.string().nullable(),
        updated_at: zod.iso.datetime({}),
        uuid: zod.uuid(),
        api_token: zod.string(),
        app_urls: zod
            .array(zod.string().max(completeProductOnboardingPartialUpdateResponseAppUrlsItemMax).nullable())
            .optional(),
        slack_incoming_webhook: zod
            .string()
            .max(completeProductOnboardingPartialUpdateResponseSlackIncomingWebhookMax)
            .nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        ingested_event: zod.boolean(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(completeProductOnboardingPartialUpdateResponsePersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(completeProductOnboardingPartialUpdateResponseSessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(completeProductOnboardingPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMin)
            .max(completeProductOnboardingPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(completeProductOnboardingPartialUpdateResponseSessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(completeProductOnboardingPartialUpdateResponseRecordingDomainsItemMax).nullable())
            .nullish(),
        person_on_events_querying_enabled: zod.string(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        default_modifiers: zod.string(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        product_intents: zod.array(
            zod.object({
                product_type: zod.string().optional(),
                created_at: zod.iso.datetime({}).optional(),
                onboarding_completed_at: zod.iso.datetime({}).nullish(),
                updated_at: zod.iso.datetime({}).optional(),
            })
        ),
        flags_persistence_default: zod.boolean().nullish(),
        secret_api_token: zod.string().nullable(),
        secret_api_token_backup: zod.string().nullable(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        available_setup_task_ids: zod.array(
            zod
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
                    'enable_revenue_analytics_viewset',
                    'connect_revenue_source',
                    'set_up_revenue_goal',
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
                ])
                .describe(
                    '* `ingest_first_event` - ingest_first_event\n* `set_up_reverse_proxy` - set_up_reverse_proxy\n* `create_first_insight` - create_first_insight\n* `create_first_dashboard` - create_first_dashboard\n* `track_custom_events` - track_custom_events\n* `define_actions` - define_actions\n* `set_up_cohorts` - set_up_cohorts\n* `explore_trends_insight` - explore_trends_insight\n* `create_funnel` - create_funnel\n* `explore_retention_insight` - explore_retention_insight\n* `explore_paths_insight` - explore_paths_insight\n* `explore_stickiness_insight` - explore_stickiness_insight\n* `explore_lifecycle_insight` - explore_lifecycle_insight\n* `add_authorized_domain` - add_authorized_domain\n* `set_up_web_vitals` - set_up_web_vitals\n* `review_web_analytics_dashboard` - review_web_analytics_dashboard\n* `filter_web_analytics` - filter_web_analytics\n* `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals\n* `visit_web_vitals_dashboard` - visit_web_vitals_dashboard\n* `setup_session_recordings` - setup_session_recordings\n* `watch_session_recording` - watch_session_recording\n* `configure_recording_settings` - configure_recording_settings\n* `create_recording_playlist` - create_recording_playlist\n* `enable_console_logs` - enable_console_logs\n* `create_feature_flag` - create_feature_flag\n* `implement_flag_in_code` - implement_flag_in_code\n* `update_feature_flag_release_conditions` - update_feature_flag_release_conditions\n* `create_multivariate_flag` - create_multivariate_flag\n* `set_up_flag_payloads` - set_up_flag_payloads\n* `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes\n* `create_experiment` - create_experiment\n* `implement_experiment_variants` - implement_experiment_variants\n* `launch_experiment` - launch_experiment\n* `review_experiment_results` - review_experiment_results\n* `create_survey` - create_survey\n* `launch_survey` - launch_survey\n* `collect_survey_responses` - collect_survey_responses\n* `connect_source` - connect_source\n* `run_first_query` - run_first_query\n* `join_external_data` - join_external_data\n* `create_saved_view` - create_saved_view\n* `enable_error_tracking` - enable_error_tracking\n* `upload_source_maps` - upload_source_maps\n* `view_first_error` - view_first_error\n* `resolve_first_error` - resolve_first_error\n* `ingest_first_llm_event` - ingest_first_llm_event\n* `view_first_trace` - view_first_trace\n* `track_costs` - track_costs\n* `set_up_llm_evaluation` - set_up_llm_evaluation\n* `run_ai_playground` - run_ai_playground\n* `enable_revenue_analytics_viewset` - enable_revenue_analytics_viewset\n* `connect_revenue_source` - connect_revenue_source\n* `set_up_revenue_goal` - set_up_revenue_goal\n* `enable_log_capture` - enable_log_capture\n* `view_first_logs` - view_first_logs\n* `create_first_workflow` - create_first_workflow\n* `set_up_first_workflow_channel` - set_up_first_workflow_channel\n* `configure_workflow_trigger` - configure_workflow_trigger\n* `add_workflow_action` - add_workflow_action\n* `launch_workflow` - launch_workflow\n* `create_first_endpoint` - create_first_endpoint\n* `configure_endpoint` - configure_endpoint\n* `test_endpoint` - test_endpoint\n* `create_early_access_feature` - create_early_access_feature\n* `update_feature_stage` - update_feature_stage'
                )
        ),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const deleteSecretTokenBackupPartialUpdateBodyNameMax = 200

export const deleteSecretTokenBackupPartialUpdateBodyProductDescriptionMax = 1000

export const deleteSecretTokenBackupPartialUpdateBodyAppUrlsItemMax = 200

export const deleteSecretTokenBackupPartialUpdateBodySlackIncomingWebhookMax = 500

export const deleteSecretTokenBackupPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const deleteSecretTokenBackupPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const deleteSecretTokenBackupPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const deleteSecretTokenBackupPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const deleteSecretTokenBackupPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const deleteSecretTokenBackupPartialUpdateBodyRecordingDomainsItemMax = 200

export const DeleteSecretTokenBackupPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().min(1).max(deleteSecretTokenBackupPartialUpdateBodyNameMax).optional(),
        product_description: zod.string().max(deleteSecretTokenBackupPartialUpdateBodyProductDescriptionMax).nullish(),
        app_urls: zod
            .array(zod.string().max(deleteSecretTokenBackupPartialUpdateBodyAppUrlsItemMax).nullable())
            .optional(),
        slack_incoming_webhook: zod
            .string()
            .max(deleteSecretTokenBackupPartialUpdateBodySlackIncomingWebhookMax)
            .nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(deleteSecretTokenBackupPartialUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(deleteSecretTokenBackupPartialUpdateBodySessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(deleteSecretTokenBackupPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(deleteSecretTokenBackupPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(deleteSecretTokenBackupPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(deleteSecretTokenBackupPartialUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        flags_persistence_default: zod.boolean().nullish(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

export const deleteSecretTokenBackupPartialUpdateResponseNameMax = 200

export const deleteSecretTokenBackupPartialUpdateResponseProductDescriptionMax = 1000

export const deleteSecretTokenBackupPartialUpdateResponseAppUrlsItemMax = 200

export const deleteSecretTokenBackupPartialUpdateResponseSlackIncomingWebhookMax = 500

export const deleteSecretTokenBackupPartialUpdateResponsePersonDisplayNamePropertiesItemMax = 400

export const deleteSecretTokenBackupPartialUpdateResponseSessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const deleteSecretTokenBackupPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMin = 0
export const deleteSecretTokenBackupPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMax = 30000

export const deleteSecretTokenBackupPartialUpdateResponseSessionRecordingTriggerMatchTypeConfigMax = 24

export const deleteSecretTokenBackupPartialUpdateResponseRecordingDomainsItemMax = 200

export const DeleteSecretTokenBackupPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        organization: zod.uuid(),
        name: zod.string().min(1).max(deleteSecretTokenBackupPartialUpdateResponseNameMax).optional(),
        product_description: zod
            .string()
            .max(deleteSecretTokenBackupPartialUpdateResponseProductDescriptionMax)
            .nullish(),
        created_at: zod.iso.datetime({}),
        effective_membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        has_group_types: zod.boolean(),
        group_types: zod.array(zod.record(zod.string(), zod.unknown())),
        live_events_token: zod.string().nullable(),
        updated_at: zod.iso.datetime({}),
        uuid: zod.uuid(),
        api_token: zod.string(),
        app_urls: zod
            .array(zod.string().max(deleteSecretTokenBackupPartialUpdateResponseAppUrlsItemMax).nullable())
            .optional(),
        slack_incoming_webhook: zod
            .string()
            .max(deleteSecretTokenBackupPartialUpdateResponseSlackIncomingWebhookMax)
            .nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        ingested_event: zod.boolean(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(deleteSecretTokenBackupPartialUpdateResponsePersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(deleteSecretTokenBackupPartialUpdateResponseSessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(deleteSecretTokenBackupPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMin)
            .max(deleteSecretTokenBackupPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(deleteSecretTokenBackupPartialUpdateResponseSessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(deleteSecretTokenBackupPartialUpdateResponseRecordingDomainsItemMax).nullable())
            .nullish(),
        person_on_events_querying_enabled: zod.string(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        default_modifiers: zod.string(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        product_intents: zod.array(
            zod.object({
                product_type: zod.string().optional(),
                created_at: zod.iso.datetime({}).optional(),
                onboarding_completed_at: zod.iso.datetime({}).nullish(),
                updated_at: zod.iso.datetime({}).optional(),
            })
        ),
        flags_persistence_default: zod.boolean().nullish(),
        secret_api_token: zod.string().nullable(),
        secret_api_token_backup: zod.string().nullable(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        available_setup_task_ids: zod.array(
            zod
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
                    'enable_revenue_analytics_viewset',
                    'connect_revenue_source',
                    'set_up_revenue_goal',
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
                ])
                .describe(
                    '* `ingest_first_event` - ingest_first_event\n* `set_up_reverse_proxy` - set_up_reverse_proxy\n* `create_first_insight` - create_first_insight\n* `create_first_dashboard` - create_first_dashboard\n* `track_custom_events` - track_custom_events\n* `define_actions` - define_actions\n* `set_up_cohorts` - set_up_cohorts\n* `explore_trends_insight` - explore_trends_insight\n* `create_funnel` - create_funnel\n* `explore_retention_insight` - explore_retention_insight\n* `explore_paths_insight` - explore_paths_insight\n* `explore_stickiness_insight` - explore_stickiness_insight\n* `explore_lifecycle_insight` - explore_lifecycle_insight\n* `add_authorized_domain` - add_authorized_domain\n* `set_up_web_vitals` - set_up_web_vitals\n* `review_web_analytics_dashboard` - review_web_analytics_dashboard\n* `filter_web_analytics` - filter_web_analytics\n* `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals\n* `visit_web_vitals_dashboard` - visit_web_vitals_dashboard\n* `setup_session_recordings` - setup_session_recordings\n* `watch_session_recording` - watch_session_recording\n* `configure_recording_settings` - configure_recording_settings\n* `create_recording_playlist` - create_recording_playlist\n* `enable_console_logs` - enable_console_logs\n* `create_feature_flag` - create_feature_flag\n* `implement_flag_in_code` - implement_flag_in_code\n* `update_feature_flag_release_conditions` - update_feature_flag_release_conditions\n* `create_multivariate_flag` - create_multivariate_flag\n* `set_up_flag_payloads` - set_up_flag_payloads\n* `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes\n* `create_experiment` - create_experiment\n* `implement_experiment_variants` - implement_experiment_variants\n* `launch_experiment` - launch_experiment\n* `review_experiment_results` - review_experiment_results\n* `create_survey` - create_survey\n* `launch_survey` - launch_survey\n* `collect_survey_responses` - collect_survey_responses\n* `connect_source` - connect_source\n* `run_first_query` - run_first_query\n* `join_external_data` - join_external_data\n* `create_saved_view` - create_saved_view\n* `enable_error_tracking` - enable_error_tracking\n* `upload_source_maps` - upload_source_maps\n* `view_first_error` - view_first_error\n* `resolve_first_error` - resolve_first_error\n* `ingest_first_llm_event` - ingest_first_llm_event\n* `view_first_trace` - view_first_trace\n* `track_costs` - track_costs\n* `set_up_llm_evaluation` - set_up_llm_evaluation\n* `run_ai_playground` - run_ai_playground\n* `enable_revenue_analytics_viewset` - enable_revenue_analytics_viewset\n* `connect_revenue_source` - connect_revenue_source\n* `set_up_revenue_goal` - set_up_revenue_goal\n* `enable_log_capture` - enable_log_capture\n* `view_first_logs` - view_first_logs\n* `create_first_workflow` - create_first_workflow\n* `set_up_first_workflow_channel` - set_up_first_workflow_channel\n* `configure_workflow_trigger` - configure_workflow_trigger\n* `add_workflow_action` - add_workflow_action\n* `launch_workflow` - launch_workflow\n* `create_first_endpoint` - create_first_endpoint\n* `configure_endpoint` - configure_endpoint\n* `test_endpoint` - test_endpoint\n* `create_early_access_feature` - create_early_access_feature\n* `update_feature_stage` - update_feature_stage'
                )
        ),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const generateConversationsPublicTokenCreateBodyNameMax = 200

export const generateConversationsPublicTokenCreateBodyProductDescriptionMax = 1000

export const generateConversationsPublicTokenCreateBodyAppUrlsItemMax = 200

export const generateConversationsPublicTokenCreateBodySlackIncomingWebhookMax = 500

export const generateConversationsPublicTokenCreateBodyPersonDisplayNamePropertiesItemMax = 400

export const generateConversationsPublicTokenCreateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const generateConversationsPublicTokenCreateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const generateConversationsPublicTokenCreateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const generateConversationsPublicTokenCreateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const generateConversationsPublicTokenCreateBodyRecordingDomainsItemMax = 200

export const GenerateConversationsPublicTokenCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().min(1).max(generateConversationsPublicTokenCreateBodyNameMax).optional(),
        product_description: zod
            .string()
            .max(generateConversationsPublicTokenCreateBodyProductDescriptionMax)
            .nullish(),
        app_urls: zod
            .array(zod.string().max(generateConversationsPublicTokenCreateBodyAppUrlsItemMax).nullable())
            .optional(),
        slack_incoming_webhook: zod
            .string()
            .max(generateConversationsPublicTokenCreateBodySlackIncomingWebhookMax)
            .nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(generateConversationsPublicTokenCreateBodyPersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(generateConversationsPublicTokenCreateBodySessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(generateConversationsPublicTokenCreateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(generateConversationsPublicTokenCreateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(generateConversationsPublicTokenCreateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(generateConversationsPublicTokenCreateBodyRecordingDomainsItemMax).nullable())
            .nullish(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        flags_persistence_default: zod.boolean().nullish(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

export const generateConversationsPublicTokenCreateResponseNameMax = 200

export const generateConversationsPublicTokenCreateResponseProductDescriptionMax = 1000

export const generateConversationsPublicTokenCreateResponseAppUrlsItemMax = 200

export const generateConversationsPublicTokenCreateResponseSlackIncomingWebhookMax = 500

export const generateConversationsPublicTokenCreateResponsePersonDisplayNamePropertiesItemMax = 400

export const generateConversationsPublicTokenCreateResponseSessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const generateConversationsPublicTokenCreateResponseSessionRecordingMinimumDurationMillisecondsMin = 0
export const generateConversationsPublicTokenCreateResponseSessionRecordingMinimumDurationMillisecondsMax = 30000

export const generateConversationsPublicTokenCreateResponseSessionRecordingTriggerMatchTypeConfigMax = 24

export const generateConversationsPublicTokenCreateResponseRecordingDomainsItemMax = 200

export const GenerateConversationsPublicTokenCreateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        organization: zod.uuid(),
        name: zod.string().min(1).max(generateConversationsPublicTokenCreateResponseNameMax).optional(),
        product_description: zod
            .string()
            .max(generateConversationsPublicTokenCreateResponseProductDescriptionMax)
            .nullish(),
        created_at: zod.iso.datetime({}),
        effective_membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        has_group_types: zod.boolean(),
        group_types: zod.array(zod.record(zod.string(), zod.unknown())),
        live_events_token: zod.string().nullable(),
        updated_at: zod.iso.datetime({}),
        uuid: zod.uuid(),
        api_token: zod.string(),
        app_urls: zod
            .array(zod.string().max(generateConversationsPublicTokenCreateResponseAppUrlsItemMax).nullable())
            .optional(),
        slack_incoming_webhook: zod
            .string()
            .max(generateConversationsPublicTokenCreateResponseSlackIncomingWebhookMax)
            .nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        ingested_event: zod.boolean(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(generateConversationsPublicTokenCreateResponsePersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(generateConversationsPublicTokenCreateResponseSessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(generateConversationsPublicTokenCreateResponseSessionRecordingMinimumDurationMillisecondsMin)
            .max(generateConversationsPublicTokenCreateResponseSessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(generateConversationsPublicTokenCreateResponseSessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(generateConversationsPublicTokenCreateResponseRecordingDomainsItemMax).nullable())
            .nullish(),
        person_on_events_querying_enabled: zod.string(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        default_modifiers: zod.string(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        product_intents: zod.array(
            zod.object({
                product_type: zod.string().optional(),
                created_at: zod.iso.datetime({}).optional(),
                onboarding_completed_at: zod.iso.datetime({}).nullish(),
                updated_at: zod.iso.datetime({}).optional(),
            })
        ),
        flags_persistence_default: zod.boolean().nullish(),
        secret_api_token: zod.string().nullable(),
        secret_api_token_backup: zod.string().nullable(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        available_setup_task_ids: zod.array(
            zod
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
                    'enable_revenue_analytics_viewset',
                    'connect_revenue_source',
                    'set_up_revenue_goal',
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
                ])
                .describe(
                    '* `ingest_first_event` - ingest_first_event\n* `set_up_reverse_proxy` - set_up_reverse_proxy\n* `create_first_insight` - create_first_insight\n* `create_first_dashboard` - create_first_dashboard\n* `track_custom_events` - track_custom_events\n* `define_actions` - define_actions\n* `set_up_cohorts` - set_up_cohorts\n* `explore_trends_insight` - explore_trends_insight\n* `create_funnel` - create_funnel\n* `explore_retention_insight` - explore_retention_insight\n* `explore_paths_insight` - explore_paths_insight\n* `explore_stickiness_insight` - explore_stickiness_insight\n* `explore_lifecycle_insight` - explore_lifecycle_insight\n* `add_authorized_domain` - add_authorized_domain\n* `set_up_web_vitals` - set_up_web_vitals\n* `review_web_analytics_dashboard` - review_web_analytics_dashboard\n* `filter_web_analytics` - filter_web_analytics\n* `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals\n* `visit_web_vitals_dashboard` - visit_web_vitals_dashboard\n* `setup_session_recordings` - setup_session_recordings\n* `watch_session_recording` - watch_session_recording\n* `configure_recording_settings` - configure_recording_settings\n* `create_recording_playlist` - create_recording_playlist\n* `enable_console_logs` - enable_console_logs\n* `create_feature_flag` - create_feature_flag\n* `implement_flag_in_code` - implement_flag_in_code\n* `update_feature_flag_release_conditions` - update_feature_flag_release_conditions\n* `create_multivariate_flag` - create_multivariate_flag\n* `set_up_flag_payloads` - set_up_flag_payloads\n* `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes\n* `create_experiment` - create_experiment\n* `implement_experiment_variants` - implement_experiment_variants\n* `launch_experiment` - launch_experiment\n* `review_experiment_results` - review_experiment_results\n* `create_survey` - create_survey\n* `launch_survey` - launch_survey\n* `collect_survey_responses` - collect_survey_responses\n* `connect_source` - connect_source\n* `run_first_query` - run_first_query\n* `join_external_data` - join_external_data\n* `create_saved_view` - create_saved_view\n* `enable_error_tracking` - enable_error_tracking\n* `upload_source_maps` - upload_source_maps\n* `view_first_error` - view_first_error\n* `resolve_first_error` - resolve_first_error\n* `ingest_first_llm_event` - ingest_first_llm_event\n* `view_first_trace` - view_first_trace\n* `track_costs` - track_costs\n* `set_up_llm_evaluation` - set_up_llm_evaluation\n* `run_ai_playground` - run_ai_playground\n* `enable_revenue_analytics_viewset` - enable_revenue_analytics_viewset\n* `connect_revenue_source` - connect_revenue_source\n* `set_up_revenue_goal` - set_up_revenue_goal\n* `enable_log_capture` - enable_log_capture\n* `view_first_logs` - view_first_logs\n* `create_first_workflow` - create_first_workflow\n* `set_up_first_workflow_channel` - set_up_first_workflow_channel\n* `configure_workflow_trigger` - configure_workflow_trigger\n* `add_workflow_action` - add_workflow_action\n* `launch_workflow` - launch_workflow\n* `create_first_endpoint` - create_first_endpoint\n* `configure_endpoint` - configure_endpoint\n* `test_endpoint` - test_endpoint\n* `create_early_access_feature` - create_early_access_feature\n* `update_feature_stage` - update_feature_stage'
                )
        ),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const isGeneratingDemoDataRetrieveResponseNameMax = 200

export const isGeneratingDemoDataRetrieveResponseProductDescriptionMax = 1000

export const isGeneratingDemoDataRetrieveResponseAppUrlsItemMax = 200

export const isGeneratingDemoDataRetrieveResponseSlackIncomingWebhookMax = 500

export const isGeneratingDemoDataRetrieveResponsePersonDisplayNamePropertiesItemMax = 400

export const isGeneratingDemoDataRetrieveResponseSessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const isGeneratingDemoDataRetrieveResponseSessionRecordingMinimumDurationMillisecondsMin = 0
export const isGeneratingDemoDataRetrieveResponseSessionRecordingMinimumDurationMillisecondsMax = 30000

export const isGeneratingDemoDataRetrieveResponseSessionRecordingTriggerMatchTypeConfigMax = 24

export const isGeneratingDemoDataRetrieveResponseRecordingDomainsItemMax = 200

export const IsGeneratingDemoDataRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        organization: zod.uuid(),
        name: zod.string().min(1).max(isGeneratingDemoDataRetrieveResponseNameMax).optional(),
        product_description: zod.string().max(isGeneratingDemoDataRetrieveResponseProductDescriptionMax).nullish(),
        created_at: zod.iso.datetime({}),
        effective_membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        has_group_types: zod.boolean(),
        group_types: zod.array(zod.record(zod.string(), zod.unknown())),
        live_events_token: zod.string().nullable(),
        updated_at: zod.iso.datetime({}),
        uuid: zod.uuid(),
        api_token: zod.string(),
        app_urls: zod.array(zod.string().max(isGeneratingDemoDataRetrieveResponseAppUrlsItemMax).nullable()).optional(),
        slack_incoming_webhook: zod.string().max(isGeneratingDemoDataRetrieveResponseSlackIncomingWebhookMax).nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        ingested_event: zod.boolean(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(isGeneratingDemoDataRetrieveResponsePersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(isGeneratingDemoDataRetrieveResponseSessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(isGeneratingDemoDataRetrieveResponseSessionRecordingMinimumDurationMillisecondsMin)
            .max(isGeneratingDemoDataRetrieveResponseSessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(isGeneratingDemoDataRetrieveResponseSessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(isGeneratingDemoDataRetrieveResponseRecordingDomainsItemMax).nullable())
            .nullish(),
        person_on_events_querying_enabled: zod.string(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        default_modifiers: zod.string(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        product_intents: zod.array(
            zod.object({
                product_type: zod.string().optional(),
                created_at: zod.iso.datetime({}).optional(),
                onboarding_completed_at: zod.iso.datetime({}).nullish(),
                updated_at: zod.iso.datetime({}).optional(),
            })
        ),
        flags_persistence_default: zod.boolean().nullish(),
        secret_api_token: zod.string().nullable(),
        secret_api_token_backup: zod.string().nullable(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        available_setup_task_ids: zod.array(
            zod
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
                    'enable_revenue_analytics_viewset',
                    'connect_revenue_source',
                    'set_up_revenue_goal',
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
                ])
                .describe(
                    '* `ingest_first_event` - ingest_first_event\n* `set_up_reverse_proxy` - set_up_reverse_proxy\n* `create_first_insight` - create_first_insight\n* `create_first_dashboard` - create_first_dashboard\n* `track_custom_events` - track_custom_events\n* `define_actions` - define_actions\n* `set_up_cohorts` - set_up_cohorts\n* `explore_trends_insight` - explore_trends_insight\n* `create_funnel` - create_funnel\n* `explore_retention_insight` - explore_retention_insight\n* `explore_paths_insight` - explore_paths_insight\n* `explore_stickiness_insight` - explore_stickiness_insight\n* `explore_lifecycle_insight` - explore_lifecycle_insight\n* `add_authorized_domain` - add_authorized_domain\n* `set_up_web_vitals` - set_up_web_vitals\n* `review_web_analytics_dashboard` - review_web_analytics_dashboard\n* `filter_web_analytics` - filter_web_analytics\n* `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals\n* `visit_web_vitals_dashboard` - visit_web_vitals_dashboard\n* `setup_session_recordings` - setup_session_recordings\n* `watch_session_recording` - watch_session_recording\n* `configure_recording_settings` - configure_recording_settings\n* `create_recording_playlist` - create_recording_playlist\n* `enable_console_logs` - enable_console_logs\n* `create_feature_flag` - create_feature_flag\n* `implement_flag_in_code` - implement_flag_in_code\n* `update_feature_flag_release_conditions` - update_feature_flag_release_conditions\n* `create_multivariate_flag` - create_multivariate_flag\n* `set_up_flag_payloads` - set_up_flag_payloads\n* `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes\n* `create_experiment` - create_experiment\n* `implement_experiment_variants` - implement_experiment_variants\n* `launch_experiment` - launch_experiment\n* `review_experiment_results` - review_experiment_results\n* `create_survey` - create_survey\n* `launch_survey` - launch_survey\n* `collect_survey_responses` - collect_survey_responses\n* `connect_source` - connect_source\n* `run_first_query` - run_first_query\n* `join_external_data` - join_external_data\n* `create_saved_view` - create_saved_view\n* `enable_error_tracking` - enable_error_tracking\n* `upload_source_maps` - upload_source_maps\n* `view_first_error` - view_first_error\n* `resolve_first_error` - resolve_first_error\n* `ingest_first_llm_event` - ingest_first_llm_event\n* `view_first_trace` - view_first_trace\n* `track_costs` - track_costs\n* `set_up_llm_evaluation` - set_up_llm_evaluation\n* `run_ai_playground` - run_ai_playground\n* `enable_revenue_analytics_viewset` - enable_revenue_analytics_viewset\n* `connect_revenue_source` - connect_revenue_source\n* `set_up_revenue_goal` - set_up_revenue_goal\n* `enable_log_capture` - enable_log_capture\n* `view_first_logs` - view_first_logs\n* `create_first_workflow` - create_first_workflow\n* `set_up_first_workflow_channel` - set_up_first_workflow_channel\n* `configure_workflow_trigger` - configure_workflow_trigger\n* `add_workflow_action` - add_workflow_action\n* `launch_workflow` - launch_workflow\n* `create_first_endpoint` - create_first_endpoint\n* `configure_endpoint` - configure_endpoint\n* `test_endpoint` - test_endpoint\n* `create_early_access_feature` - create_early_access_feature\n* `update_feature_stage` - update_feature_stage'
                )
        ),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const resetTokenPartialUpdateBodyNameMax = 200

export const resetTokenPartialUpdateBodyProductDescriptionMax = 1000

export const resetTokenPartialUpdateBodyAppUrlsItemMax = 200

export const resetTokenPartialUpdateBodySlackIncomingWebhookMax = 500

export const resetTokenPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const resetTokenPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const resetTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const resetTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const resetTokenPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const resetTokenPartialUpdateBodyRecordingDomainsItemMax = 200

export const ResetTokenPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().min(1).max(resetTokenPartialUpdateBodyNameMax).optional(),
        product_description: zod.string().max(resetTokenPartialUpdateBodyProductDescriptionMax).nullish(),
        app_urls: zod.array(zod.string().max(resetTokenPartialUpdateBodyAppUrlsItemMax).nullable()).optional(),
        slack_incoming_webhook: zod.string().max(resetTokenPartialUpdateBodySlackIncomingWebhookMax).nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(resetTokenPartialUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(resetTokenPartialUpdateBodySessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(resetTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(resetTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(resetTokenPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(resetTokenPartialUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        flags_persistence_default: zod.boolean().nullish(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

export const resetTokenPartialUpdateResponseNameMax = 200

export const resetTokenPartialUpdateResponseProductDescriptionMax = 1000

export const resetTokenPartialUpdateResponseAppUrlsItemMax = 200

export const resetTokenPartialUpdateResponseSlackIncomingWebhookMax = 500

export const resetTokenPartialUpdateResponsePersonDisplayNamePropertiesItemMax = 400

export const resetTokenPartialUpdateResponseSessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const resetTokenPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMin = 0
export const resetTokenPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMax = 30000

export const resetTokenPartialUpdateResponseSessionRecordingTriggerMatchTypeConfigMax = 24

export const resetTokenPartialUpdateResponseRecordingDomainsItemMax = 200

export const ResetTokenPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        organization: zod.uuid(),
        name: zod.string().min(1).max(resetTokenPartialUpdateResponseNameMax).optional(),
        product_description: zod.string().max(resetTokenPartialUpdateResponseProductDescriptionMax).nullish(),
        created_at: zod.iso.datetime({}),
        effective_membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        has_group_types: zod.boolean(),
        group_types: zod.array(zod.record(zod.string(), zod.unknown())),
        live_events_token: zod.string().nullable(),
        updated_at: zod.iso.datetime({}),
        uuid: zod.uuid(),
        api_token: zod.string(),
        app_urls: zod.array(zod.string().max(resetTokenPartialUpdateResponseAppUrlsItemMax).nullable()).optional(),
        slack_incoming_webhook: zod.string().max(resetTokenPartialUpdateResponseSlackIncomingWebhookMax).nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        ingested_event: zod.boolean(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(resetTokenPartialUpdateResponsePersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(resetTokenPartialUpdateResponseSessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(resetTokenPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMin)
            .max(resetTokenPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(resetTokenPartialUpdateResponseSessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(resetTokenPartialUpdateResponseRecordingDomainsItemMax).nullable())
            .nullish(),
        person_on_events_querying_enabled: zod.string(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        default_modifiers: zod.string(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        product_intents: zod.array(
            zod.object({
                product_type: zod.string().optional(),
                created_at: zod.iso.datetime({}).optional(),
                onboarding_completed_at: zod.iso.datetime({}).nullish(),
                updated_at: zod.iso.datetime({}).optional(),
            })
        ),
        flags_persistence_default: zod.boolean().nullish(),
        secret_api_token: zod.string().nullable(),
        secret_api_token_backup: zod.string().nullable(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        available_setup_task_ids: zod.array(
            zod
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
                    'enable_revenue_analytics_viewset',
                    'connect_revenue_source',
                    'set_up_revenue_goal',
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
                ])
                .describe(
                    '* `ingest_first_event` - ingest_first_event\n* `set_up_reverse_proxy` - set_up_reverse_proxy\n* `create_first_insight` - create_first_insight\n* `create_first_dashboard` - create_first_dashboard\n* `track_custom_events` - track_custom_events\n* `define_actions` - define_actions\n* `set_up_cohorts` - set_up_cohorts\n* `explore_trends_insight` - explore_trends_insight\n* `create_funnel` - create_funnel\n* `explore_retention_insight` - explore_retention_insight\n* `explore_paths_insight` - explore_paths_insight\n* `explore_stickiness_insight` - explore_stickiness_insight\n* `explore_lifecycle_insight` - explore_lifecycle_insight\n* `add_authorized_domain` - add_authorized_domain\n* `set_up_web_vitals` - set_up_web_vitals\n* `review_web_analytics_dashboard` - review_web_analytics_dashboard\n* `filter_web_analytics` - filter_web_analytics\n* `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals\n* `visit_web_vitals_dashboard` - visit_web_vitals_dashboard\n* `setup_session_recordings` - setup_session_recordings\n* `watch_session_recording` - watch_session_recording\n* `configure_recording_settings` - configure_recording_settings\n* `create_recording_playlist` - create_recording_playlist\n* `enable_console_logs` - enable_console_logs\n* `create_feature_flag` - create_feature_flag\n* `implement_flag_in_code` - implement_flag_in_code\n* `update_feature_flag_release_conditions` - update_feature_flag_release_conditions\n* `create_multivariate_flag` - create_multivariate_flag\n* `set_up_flag_payloads` - set_up_flag_payloads\n* `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes\n* `create_experiment` - create_experiment\n* `implement_experiment_variants` - implement_experiment_variants\n* `launch_experiment` - launch_experiment\n* `review_experiment_results` - review_experiment_results\n* `create_survey` - create_survey\n* `launch_survey` - launch_survey\n* `collect_survey_responses` - collect_survey_responses\n* `connect_source` - connect_source\n* `run_first_query` - run_first_query\n* `join_external_data` - join_external_data\n* `create_saved_view` - create_saved_view\n* `enable_error_tracking` - enable_error_tracking\n* `upload_source_maps` - upload_source_maps\n* `view_first_error` - view_first_error\n* `resolve_first_error` - resolve_first_error\n* `ingest_first_llm_event` - ingest_first_llm_event\n* `view_first_trace` - view_first_trace\n* `track_costs` - track_costs\n* `set_up_llm_evaluation` - set_up_llm_evaluation\n* `run_ai_playground` - run_ai_playground\n* `enable_revenue_analytics_viewset` - enable_revenue_analytics_viewset\n* `connect_revenue_source` - connect_revenue_source\n* `set_up_revenue_goal` - set_up_revenue_goal\n* `enable_log_capture` - enable_log_capture\n* `view_first_logs` - view_first_logs\n* `create_first_workflow` - create_first_workflow\n* `set_up_first_workflow_channel` - set_up_first_workflow_channel\n* `configure_workflow_trigger` - configure_workflow_trigger\n* `add_workflow_action` - add_workflow_action\n* `launch_workflow` - launch_workflow\n* `create_first_endpoint` - create_first_endpoint\n* `configure_endpoint` - configure_endpoint\n* `test_endpoint` - test_endpoint\n* `create_early_access_feature` - create_early_access_feature\n* `update_feature_stage` - update_feature_stage'
                )
        ),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const rotateSecretTokenPartialUpdateBodyNameMax = 200

export const rotateSecretTokenPartialUpdateBodyProductDescriptionMax = 1000

export const rotateSecretTokenPartialUpdateBodyAppUrlsItemMax = 200

export const rotateSecretTokenPartialUpdateBodySlackIncomingWebhookMax = 500

export const rotateSecretTokenPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const rotateSecretTokenPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const rotateSecretTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const rotateSecretTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const rotateSecretTokenPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const rotateSecretTokenPartialUpdateBodyRecordingDomainsItemMax = 200

export const RotateSecretTokenPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().min(1).max(rotateSecretTokenPartialUpdateBodyNameMax).optional(),
        product_description: zod.string().max(rotateSecretTokenPartialUpdateBodyProductDescriptionMax).nullish(),
        app_urls: zod.array(zod.string().max(rotateSecretTokenPartialUpdateBodyAppUrlsItemMax).nullable()).optional(),
        slack_incoming_webhook: zod.string().max(rotateSecretTokenPartialUpdateBodySlackIncomingWebhookMax).nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(rotateSecretTokenPartialUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(rotateSecretTokenPartialUpdateBodySessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(rotateSecretTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(rotateSecretTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(rotateSecretTokenPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(rotateSecretTokenPartialUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        flags_persistence_default: zod.boolean().nullish(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

export const rotateSecretTokenPartialUpdateResponseNameMax = 200

export const rotateSecretTokenPartialUpdateResponseProductDescriptionMax = 1000

export const rotateSecretTokenPartialUpdateResponseAppUrlsItemMax = 200

export const rotateSecretTokenPartialUpdateResponseSlackIncomingWebhookMax = 500

export const rotateSecretTokenPartialUpdateResponsePersonDisplayNamePropertiesItemMax = 400

export const rotateSecretTokenPartialUpdateResponseSessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const rotateSecretTokenPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMin = 0
export const rotateSecretTokenPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMax = 30000

export const rotateSecretTokenPartialUpdateResponseSessionRecordingTriggerMatchTypeConfigMax = 24

export const rotateSecretTokenPartialUpdateResponseRecordingDomainsItemMax = 200

export const RotateSecretTokenPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        organization: zod.uuid(),
        name: zod.string().min(1).max(rotateSecretTokenPartialUpdateResponseNameMax).optional(),
        product_description: zod.string().max(rotateSecretTokenPartialUpdateResponseProductDescriptionMax).nullish(),
        created_at: zod.iso.datetime({}),
        effective_membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        has_group_types: zod.boolean(),
        group_types: zod.array(zod.record(zod.string(), zod.unknown())),
        live_events_token: zod.string().nullable(),
        updated_at: zod.iso.datetime({}),
        uuid: zod.uuid(),
        api_token: zod.string(),
        app_urls: zod
            .array(zod.string().max(rotateSecretTokenPartialUpdateResponseAppUrlsItemMax).nullable())
            .optional(),
        slack_incoming_webhook: zod
            .string()
            .max(rotateSecretTokenPartialUpdateResponseSlackIncomingWebhookMax)
            .nullish(),
        anonymize_ips: zod.boolean().optional(),
        completed_snippet_onboarding: zod.boolean().optional(),
        ingested_event: zod.boolean(),
        test_account_filters: zod.unknown().optional(),
        test_account_filters_default_checked: zod.boolean().nullish(),
        path_cleaning_filters: zod.unknown().nullish(),
        is_demo: zod.boolean().optional(),
        timezone: zod.string().optional(),
        data_attributes: zod.unknown().optional(),
        person_display_name_properties: zod
            .array(zod.string().max(rotateSecretTokenPartialUpdateResponsePersonDisplayNamePropertiesItemMax))
            .nullish(),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod.boolean().nullish(),
        autocapture_exceptions_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_opt_in: zod.boolean().nullish(),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod.boolean().nullish(),
        capture_performance_opt_in: zod.boolean().nullish(),
        session_recording_opt_in: zod.boolean().optional(),
        session_recording_sample_rate: zod
            .string()
            .regex(rotateSecretTokenPartialUpdateResponseSessionRecordingSampleRateRegExp)
            .nullish(),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(rotateSecretTokenPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMin)
            .max(rotateSecretTokenPartialUpdateResponseSessionRecordingMinimumDurationMillisecondsMax)
            .nullish(),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(rotateSecretTokenPartialUpdateResponseSessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .optional()
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish(),
        primary_dashboard: zod.number().nullish(),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(rotateSecretTokenPartialUpdateResponseRecordingDomainsItemMax).nullable())
            .nullish(),
        person_on_events_querying_enabled: zod.string(),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        default_modifiers: zod.string(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod.boolean().nullish(),
        heatmaps_opt_in: zod.boolean().nullish(),
        product_intents: zod.array(
            zod.object({
                product_type: zod.string().optional(),
                created_at: zod.iso.datetime({}).optional(),
                onboarding_completed_at: zod.iso.datetime({}).nullish(),
                updated_at: zod.iso.datetime({}).optional(),
            })
        ),
        flags_persistence_default: zod.boolean().nullish(),
        secret_api_token: zod.string().nullable(),
        secret_api_token_backup: zod.string().nullable(),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers, used to optimize the UI layout.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod.boolean().nullish(),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
        available_setup_task_ids: zod.array(
            zod
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
                    'enable_revenue_analytics_viewset',
                    'connect_revenue_source',
                    'set_up_revenue_goal',
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
                ])
                .describe(
                    '* `ingest_first_event` - ingest_first_event\n* `set_up_reverse_proxy` - set_up_reverse_proxy\n* `create_first_insight` - create_first_insight\n* `create_first_dashboard` - create_first_dashboard\n* `track_custom_events` - track_custom_events\n* `define_actions` - define_actions\n* `set_up_cohorts` - set_up_cohorts\n* `explore_trends_insight` - explore_trends_insight\n* `create_funnel` - create_funnel\n* `explore_retention_insight` - explore_retention_insight\n* `explore_paths_insight` - explore_paths_insight\n* `explore_stickiness_insight` - explore_stickiness_insight\n* `explore_lifecycle_insight` - explore_lifecycle_insight\n* `add_authorized_domain` - add_authorized_domain\n* `set_up_web_vitals` - set_up_web_vitals\n* `review_web_analytics_dashboard` - review_web_analytics_dashboard\n* `filter_web_analytics` - filter_web_analytics\n* `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals\n* `visit_web_vitals_dashboard` - visit_web_vitals_dashboard\n* `setup_session_recordings` - setup_session_recordings\n* `watch_session_recording` - watch_session_recording\n* `configure_recording_settings` - configure_recording_settings\n* `create_recording_playlist` - create_recording_playlist\n* `enable_console_logs` - enable_console_logs\n* `create_feature_flag` - create_feature_flag\n* `implement_flag_in_code` - implement_flag_in_code\n* `update_feature_flag_release_conditions` - update_feature_flag_release_conditions\n* `create_multivariate_flag` - create_multivariate_flag\n* `set_up_flag_payloads` - set_up_flag_payloads\n* `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes\n* `create_experiment` - create_experiment\n* `implement_experiment_variants` - implement_experiment_variants\n* `launch_experiment` - launch_experiment\n* `review_experiment_results` - review_experiment_results\n* `create_survey` - create_survey\n* `launch_survey` - launch_survey\n* `collect_survey_responses` - collect_survey_responses\n* `connect_source` - connect_source\n* `run_first_query` - run_first_query\n* `join_external_data` - join_external_data\n* `create_saved_view` - create_saved_view\n* `enable_error_tracking` - enable_error_tracking\n* `upload_source_maps` - upload_source_maps\n* `view_first_error` - view_first_error\n* `resolve_first_error` - resolve_first_error\n* `ingest_first_llm_event` - ingest_first_llm_event\n* `view_first_trace` - view_first_trace\n* `track_costs` - track_costs\n* `set_up_llm_evaluation` - set_up_llm_evaluation\n* `run_ai_playground` - run_ai_playground\n* `enable_revenue_analytics_viewset` - enable_revenue_analytics_viewset\n* `connect_revenue_source` - connect_revenue_source\n* `set_up_revenue_goal` - set_up_revenue_goal\n* `enable_log_capture` - enable_log_capture\n* `view_first_logs` - view_first_logs\n* `create_first_workflow` - create_first_workflow\n* `set_up_first_workflow_channel` - set_up_first_workflow_channel\n* `configure_workflow_trigger` - configure_workflow_trigger\n* `add_workflow_action` - add_workflow_action\n* `launch_workflow` - launch_workflow\n* `create_first_endpoint` - create_first_endpoint\n* `configure_endpoint` - configure_endpoint\n* `test_endpoint` - test_endpoint\n* `create_early_access_feature` - create_early_access_feature\n* `update_feature_stage` - update_feature_stage'
                )
        ),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

export const dashboardTemplatesRetrieveResponseTemplateNameMax = 400

export const dashboardTemplatesRetrieveResponseDashboardDescriptionMax = 400

export const dashboardTemplatesRetrieveResponseTagsItemMax = 255

export const dashboardTemplatesRetrieveResponseCreatedByOneDistinctIdMax = 200

export const dashboardTemplatesRetrieveResponseCreatedByOneFirstNameMax = 150

export const dashboardTemplatesRetrieveResponseCreatedByOneLastNameMax = 150

export const dashboardTemplatesRetrieveResponseCreatedByOneEmailMax = 254

export const dashboardTemplatesRetrieveResponseImageUrlMax = 8201

export const dashboardTemplatesRetrieveResponseAvailabilityContextsItemMax = 255

export const DashboardTemplatesRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    template_name: zod.string().max(dashboardTemplatesRetrieveResponseTemplateNameMax).nullish(),
    dashboard_description: zod.string().max(dashboardTemplatesRetrieveResponseDashboardDescriptionMax).nullish(),
    dashboard_filters: zod.unknown().nullish(),
    tags: zod.array(zod.string().max(dashboardTemplatesRetrieveResponseTagsItemMax)).nullish(),
    tiles: zod.unknown().nullish(),
    variables: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
    created_at: zod.iso.datetime({}).nullable(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(dashboardTemplatesRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(dashboardTemplatesRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(dashboardTemplatesRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(dashboardTemplatesRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    image_url: zod.string().max(dashboardTemplatesRetrieveResponseImageUrlMax).nullish(),
    team_id: zod.number().nullable(),
    scope: zod
        .union([
            zod
                .enum(['team', 'global', 'feature_flag'])
                .describe('* `team` - Only team\n* `global` - Global\n* `feature_flag` - Feature Flag'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    availability_contexts: zod
        .array(zod.string().max(dashboardTemplatesRetrieveResponseAvailabilityContextsItemMax))
        .nullish(),
    is_featured: zod.boolean().optional().describe('Manually curated; used to highlight templates in the UI.'),
})

export const dashboardTemplatesUpdateBodyTemplateNameMax = 400

export const dashboardTemplatesUpdateBodyDashboardDescriptionMax = 400

export const dashboardTemplatesUpdateBodyTagsItemMax = 255

export const dashboardTemplatesUpdateBodyImageUrlMax = 8201

export const dashboardTemplatesUpdateBodyAvailabilityContextsItemMax = 255

export const DashboardTemplatesUpdateBody = /* @__PURE__ */ zod.object({
    template_name: zod.string().max(dashboardTemplatesUpdateBodyTemplateNameMax).nullish(),
    dashboard_description: zod.string().max(dashboardTemplatesUpdateBodyDashboardDescriptionMax).nullish(),
    dashboard_filters: zod.unknown().nullish(),
    tags: zod.array(zod.string().max(dashboardTemplatesUpdateBodyTagsItemMax)).nullish(),
    tiles: zod.unknown().nullish(),
    variables: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
    image_url: zod.string().max(dashboardTemplatesUpdateBodyImageUrlMax).nullish(),
    scope: zod
        .union([
            zod
                .enum(['team', 'global', 'feature_flag'])
                .describe('* `team` - Only team\n* `global` - Global\n* `feature_flag` - Feature Flag'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    availability_contexts: zod
        .array(zod.string().max(dashboardTemplatesUpdateBodyAvailabilityContextsItemMax))
        .nullish(),
    is_featured: zod.boolean().optional().describe('Manually curated; used to highlight templates in the UI.'),
})

export const dashboardTemplatesUpdateResponseTemplateNameMax = 400

export const dashboardTemplatesUpdateResponseDashboardDescriptionMax = 400

export const dashboardTemplatesUpdateResponseTagsItemMax = 255

export const dashboardTemplatesUpdateResponseCreatedByOneDistinctIdMax = 200

export const dashboardTemplatesUpdateResponseCreatedByOneFirstNameMax = 150

export const dashboardTemplatesUpdateResponseCreatedByOneLastNameMax = 150

export const dashboardTemplatesUpdateResponseCreatedByOneEmailMax = 254

export const dashboardTemplatesUpdateResponseImageUrlMax = 8201

export const dashboardTemplatesUpdateResponseAvailabilityContextsItemMax = 255

export const DashboardTemplatesUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    template_name: zod.string().max(dashboardTemplatesUpdateResponseTemplateNameMax).nullish(),
    dashboard_description: zod.string().max(dashboardTemplatesUpdateResponseDashboardDescriptionMax).nullish(),
    dashboard_filters: zod.unknown().nullish(),
    tags: zod.array(zod.string().max(dashboardTemplatesUpdateResponseTagsItemMax)).nullish(),
    tiles: zod.unknown().nullish(),
    variables: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
    created_at: zod.iso.datetime({}).nullable(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(dashboardTemplatesUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(dashboardTemplatesUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(dashboardTemplatesUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(dashboardTemplatesUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    image_url: zod.string().max(dashboardTemplatesUpdateResponseImageUrlMax).nullish(),
    team_id: zod.number().nullable(),
    scope: zod
        .union([
            zod
                .enum(['team', 'global', 'feature_flag'])
                .describe('* `team` - Only team\n* `global` - Global\n* `feature_flag` - Feature Flag'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    availability_contexts: zod
        .array(zod.string().max(dashboardTemplatesUpdateResponseAvailabilityContextsItemMax))
        .nullish(),
    is_featured: zod.boolean().optional().describe('Manually curated; used to highlight templates in the UI.'),
})

export const dashboardTemplatesPartialUpdateBodyTemplateNameMax = 400

export const dashboardTemplatesPartialUpdateBodyDashboardDescriptionMax = 400

export const dashboardTemplatesPartialUpdateBodyTagsItemMax = 255

export const dashboardTemplatesPartialUpdateBodyImageUrlMax = 8201

export const dashboardTemplatesPartialUpdateBodyAvailabilityContextsItemMax = 255

export const DashboardTemplatesPartialUpdateBody = /* @__PURE__ */ zod.object({
    template_name: zod.string().max(dashboardTemplatesPartialUpdateBodyTemplateNameMax).nullish(),
    dashboard_description: zod.string().max(dashboardTemplatesPartialUpdateBodyDashboardDescriptionMax).nullish(),
    dashboard_filters: zod.unknown().nullish(),
    tags: zod.array(zod.string().max(dashboardTemplatesPartialUpdateBodyTagsItemMax)).nullish(),
    tiles: zod.unknown().nullish(),
    variables: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
    image_url: zod.string().max(dashboardTemplatesPartialUpdateBodyImageUrlMax).nullish(),
    scope: zod
        .union([
            zod
                .enum(['team', 'global', 'feature_flag'])
                .describe('* `team` - Only team\n* `global` - Global\n* `feature_flag` - Feature Flag'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    availability_contexts: zod
        .array(zod.string().max(dashboardTemplatesPartialUpdateBodyAvailabilityContextsItemMax))
        .nullish(),
    is_featured: zod.boolean().optional().describe('Manually curated; used to highlight templates in the UI.'),
})

export const dashboardTemplatesPartialUpdateResponseTemplateNameMax = 400

export const dashboardTemplatesPartialUpdateResponseDashboardDescriptionMax = 400

export const dashboardTemplatesPartialUpdateResponseTagsItemMax = 255

export const dashboardTemplatesPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const dashboardTemplatesPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const dashboardTemplatesPartialUpdateResponseCreatedByOneLastNameMax = 150

export const dashboardTemplatesPartialUpdateResponseCreatedByOneEmailMax = 254

export const dashboardTemplatesPartialUpdateResponseImageUrlMax = 8201

export const dashboardTemplatesPartialUpdateResponseAvailabilityContextsItemMax = 255

export const DashboardTemplatesPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    template_name: zod.string().max(dashboardTemplatesPartialUpdateResponseTemplateNameMax).nullish(),
    dashboard_description: zod.string().max(dashboardTemplatesPartialUpdateResponseDashboardDescriptionMax).nullish(),
    dashboard_filters: zod.unknown().nullish(),
    tags: zod.array(zod.string().max(dashboardTemplatesPartialUpdateResponseTagsItemMax)).nullish(),
    tiles: zod.unknown().nullish(),
    variables: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
    created_at: zod.iso.datetime({}).nullable(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(dashboardTemplatesPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(dashboardTemplatesPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(dashboardTemplatesPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(dashboardTemplatesPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    image_url: zod.string().max(dashboardTemplatesPartialUpdateResponseImageUrlMax).nullish(),
    team_id: zod.number().nullable(),
    scope: zod
        .union([
            zod
                .enum(['team', 'global', 'feature_flag'])
                .describe('* `team` - Only team\n* `global` - Global\n* `feature_flag` - Feature Flag'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    availability_contexts: zod
        .array(zod.string().max(dashboardTemplatesPartialUpdateResponseAvailabilityContextsItemMax))
        .nullish(),
    is_featured: zod.boolean().optional().describe('Manually curated; used to highlight templates in the UI.'),
})

export const ExportsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.number(),
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
                        '* `image/png` - image/png\n* `application/pdf` - application/pdf\n* `text/csv` - text/csv\n* `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\n* `video/webm` - video/webm\n* `video/mp4` - video/mp4\n* `image/gif` - image/gif\n* `application/json` - application/json'
                    ),
                created_at: zod.iso.datetime({}),
                has_content: zod.boolean(),
                export_context: zod.unknown().nullish(),
                filename: zod.string(),
                expires_after: zod.iso.datetime({}).nullable(),
                exception: zod.string().nullable(),
            })
            .describe("Standard ExportedAsset serializer that doesn't return content.")
    ),
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
                '* `image/png` - image/png\n* `application/pdf` - application/pdf\n* `text/csv` - text/csv\n* `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\n* `video/webm` - video/webm\n* `video/mp4` - video/mp4\n* `image/gif` - image/gif\n* `application/json` - application/json'
            ),
        export_context: zod.unknown().nullish(),
    })
    .describe("Standard ExportedAsset serializer that doesn't return content.")

export const ExportsRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
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
                '* `image/png` - image/png\n* `application/pdf` - application/pdf\n* `text/csv` - text/csv\n* `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\n* `video/webm` - video/webm\n* `video/mp4` - video/mp4\n* `image/gif` - image/gif\n* `application/json` - application/json'
            ),
        created_at: zod.iso.datetime({}),
        has_content: zod.boolean(),
        export_context: zod.unknown().nullish(),
        filename: zod.string(),
        expires_after: zod.iso.datetime({}).nullable(),
        exception: zod.string().nullable(),
    })
    .describe("Standard ExportedAsset serializer that doesn't return content.")

export const fileSystemListResponseResultsItemTypeMax = 100

export const fileSystemListResponseResultsItemRefMax = 100

export const FileSystemListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            path: zod.string(),
            depth: zod.number().nullable(),
            type: zod.string().max(fileSystemListResponseResultsItemTypeMax).optional(),
            ref: zod.string().max(fileSystemListResponseResultsItemRefMax).nullish(),
            href: zod.string().nullish(),
            meta: zod.unknown().nullish(),
            shortcut: zod.boolean().nullish(),
            created_at: zod.iso.datetime({}),
            last_viewed_at: zod.iso.datetime({}).nullable(),
        })
    ),
})

export const fileSystemCreateBodyTypeMax = 100

export const fileSystemCreateBodyRefMax = 100

export const FileSystemCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemRetrieveResponseTypeMax = 100

export const fileSystemRetrieveResponseRefMax = 100

export const FileSystemRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    path: zod.string(),
    depth: zod.number().nullable(),
    type: zod.string().max(fileSystemRetrieveResponseTypeMax).optional(),
    ref: zod.string().max(fileSystemRetrieveResponseRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
    created_at: zod.iso.datetime({}),
    last_viewed_at: zod.iso.datetime({}).nullable(),
})

export const fileSystemUpdateBodyTypeMax = 100

export const fileSystemUpdateBodyRefMax = 100

export const FileSystemUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemUpdateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemUpdateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemUpdateResponseTypeMax = 100

export const fileSystemUpdateResponseRefMax = 100

export const FileSystemUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    path: zod.string(),
    depth: zod.number().nullable(),
    type: zod.string().max(fileSystemUpdateResponseTypeMax).optional(),
    ref: zod.string().max(fileSystemUpdateResponseRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
    created_at: zod.iso.datetime({}),
    last_viewed_at: zod.iso.datetime({}).nullable(),
})

export const fileSystemPartialUpdateBodyTypeMax = 100

export const fileSystemPartialUpdateBodyRefMax = 100

export const FileSystemPartialUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string().optional(),
    type: zod.string().max(fileSystemPartialUpdateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemPartialUpdateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemPartialUpdateResponseTypeMax = 100

export const fileSystemPartialUpdateResponseRefMax = 100

export const FileSystemPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    path: zod.string(),
    depth: zod.number().nullable(),
    type: zod.string().max(fileSystemPartialUpdateResponseTypeMax).optional(),
    ref: zod.string().max(fileSystemPartialUpdateResponseRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
    created_at: zod.iso.datetime({}),
    last_viewed_at: zod.iso.datetime({}).nullable(),
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
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemLinkCreateBodyTypeMax = 100

export const fileSystemLinkCreateBodyRefMax = 100

export const FileSystemLinkCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemLinkCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemLinkCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemMoveCreateBodyTypeMax = 100

export const fileSystemMoveCreateBodyRefMax = 100

export const FileSystemMoveCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemMoveCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemMoveCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
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
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemLogViewCreateBodyTypeMax = 100

export const fileSystemLogViewCreateBodyRefMax = 100

export const FileSystemLogViewCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemLogViewCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemLogViewCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemUndoDeleteCreateBodyTypeMax = 100

export const fileSystemUndoDeleteCreateBodyRefMax = 100

export const FileSystemUndoDeleteCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemUndoDeleteCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemUndoDeleteCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Get possible values for a feature flag.

Query parameters:
- key: The flag ID (required)
Returns:

- Array of objects with 'name' field containing possible values
 */
export const FlagValueValuesRetrieveResponse = /* @__PURE__ */ zod.object({
    results: zod.array(
        zod.object({
            name: zod.unknown(),
        })
    ),
    refreshing: zod.boolean(),
})

export const insightsSharingListResponseSharePasswordsItemNoteMax = 100

export const InsightsSharingListResponseItem = /* @__PURE__ */ zod.object({
    created_at: zod.iso.datetime({}),
    enabled: zod.boolean().optional(),
    access_token: zod.string().nullable(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
    share_passwords: zod.array(
        zod.object({
            id: zod.number(),
            created_at: zod.iso.datetime({}),
            note: zod.string().max(insightsSharingListResponseSharePasswordsItemNoteMax).nullish(),
            created_by_email: zod.string(),
            is_active: zod.boolean(),
        })
    ),
})
export const InsightsSharingListResponse = /* @__PURE__ */ zod.array(InsightsSharingListResponseItem)

/**
 * Create a new password for the sharing configuration.
 */
export const InsightsSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const insightsSharingPasswordsCreateResponseSharePasswordsItemNoteMax = 100

export const InsightsSharingPasswordsCreateResponse = /* @__PURE__ */ zod.object({
    created_at: zod.iso.datetime({}),
    enabled: zod.boolean().optional(),
    access_token: zod.string().nullable(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
    share_passwords: zod.array(
        zod.object({
            id: zod.number(),
            created_at: zod.iso.datetime({}),
            note: zod.string().max(insightsSharingPasswordsCreateResponseSharePasswordsItemNoteMax).nullish(),
            created_by_email: zod.string(),
            is_active: zod.boolean(),
        })
    ),
})

export const InsightsSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const insightsSharingRefreshCreateResponseSharePasswordsItemNoteMax = 100

export const InsightsSharingRefreshCreateResponse = /* @__PURE__ */ zod.object({
    created_at: zod.iso.datetime({}),
    enabled: zod.boolean().optional(),
    access_token: zod.string().nullable(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
    share_passwords: zod.array(
        zod.object({
            id: zod.number(),
            created_at: zod.iso.datetime({}),
            note: zod.string().max(insightsSharingRefreshCreateResponseSharePasswordsItemNoteMax).nullish(),
            created_by_email: zod.string(),
            is_active: zod.boolean(),
        })
    ),
})

export const projectSecretApiKeysListResponseResultsItemLabelMax = 40

export const ProjectSecretApiKeysListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            label: zod.string().max(projectSecretApiKeysListResponseResultsItemLabelMax),
            value: zod.string(),
            mask_value: zod.string().nullable(),
            created_at: zod.iso.datetime({}),
            created_by: zod.number().nullable(),
            last_used_at: zod.iso.datetime({}).nullable(),
            last_rolled_at: zod.iso.datetime({}).nullable(),
            scopes: zod.array(zod.string()),
        })
    ),
})

export const projectSecretApiKeysCreateBodyLabelMax = 40

export const ProjectSecretApiKeysCreateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysCreateBodyLabelMax),
    scopes: zod.array(zod.string()),
})

export const projectSecretApiKeysRetrieveResponseLabelMax = 40

export const ProjectSecretApiKeysRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.string(),
    label: zod.string().max(projectSecretApiKeysRetrieveResponseLabelMax),
    value: zod.string(),
    mask_value: zod.string().nullable(),
    created_at: zod.iso.datetime({}),
    created_by: zod.number().nullable(),
    last_used_at: zod.iso.datetime({}).nullable(),
    last_rolled_at: zod.iso.datetime({}).nullable(),
    scopes: zod.array(zod.string()),
})

export const projectSecretApiKeysUpdateBodyLabelMax = 40

export const ProjectSecretApiKeysUpdateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysUpdateBodyLabelMax),
    scopes: zod.array(zod.string()),
})

export const projectSecretApiKeysUpdateResponseLabelMax = 40

export const ProjectSecretApiKeysUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.string(),
    label: zod.string().max(projectSecretApiKeysUpdateResponseLabelMax),
    value: zod.string(),
    mask_value: zod.string().nullable(),
    created_at: zod.iso.datetime({}),
    created_by: zod.number().nullable(),
    last_used_at: zod.iso.datetime({}).nullable(),
    last_rolled_at: zod.iso.datetime({}).nullable(),
    scopes: zod.array(zod.string()),
})

export const projectSecretApiKeysPartialUpdateBodyLabelMax = 40

export const ProjectSecretApiKeysPartialUpdateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysPartialUpdateBodyLabelMax).optional(),
    scopes: zod.array(zod.string()).optional(),
})

export const projectSecretApiKeysPartialUpdateResponseLabelMax = 40

export const ProjectSecretApiKeysPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.string(),
    label: zod.string().max(projectSecretApiKeysPartialUpdateResponseLabelMax),
    value: zod.string(),
    mask_value: zod.string().nullable(),
    created_at: zod.iso.datetime({}),
    created_by: zod.number().nullable(),
    last_used_at: zod.iso.datetime({}).nullable(),
    last_rolled_at: zod.iso.datetime({}).nullable(),
    scopes: zod.array(zod.string()),
})

/**
 * Roll a project secret API key
 */
export const projectSecretApiKeysRollCreateResponseLabelMax = 40

export const ProjectSecretApiKeysRollCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.string(),
    label: zod.string().max(projectSecretApiKeysRollCreateResponseLabelMax),
    value: zod.string(),
    mask_value: zod.string().nullable(),
    created_at: zod.iso.datetime({}),
    created_by: zod.number().nullable(),
    last_used_at: zod.iso.datetime({}).nullable(),
    last_rolled_at: zod.iso.datetime({}).nullable(),
    scopes: zod.array(zod.string()),
})

export const propertyDefinitionsListResponseResultsItemUpdatedByOneDistinctIdMax = 200

export const propertyDefinitionsListResponseResultsItemUpdatedByOneFirstNameMax = 150

export const propertyDefinitionsListResponseResultsItemUpdatedByOneLastNameMax = 150

export const propertyDefinitionsListResponseResultsItemUpdatedByOneEmailMax = 254

export const propertyDefinitionsListResponseResultsItemVerifiedByOneDistinctIdMax = 200

export const propertyDefinitionsListResponseResultsItemVerifiedByOneFirstNameMax = 150

export const propertyDefinitionsListResponseResultsItemVerifiedByOneLastNameMax = 150

export const propertyDefinitionsListResponseResultsItemVerifiedByOneEmailMax = 254

export const PropertyDefinitionsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid(),
                name: zod.string(),
                description: zod.string().nullish(),
                tags: zod.array(zod.unknown()).optional(),
                is_numerical: zod.boolean(),
                updated_at: zod.iso.datetime({}),
                updated_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(propertyDefinitionsListResponseResultsItemUpdatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(propertyDefinitionsListResponseResultsItemUpdatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(propertyDefinitionsListResponseResultsItemUpdatedByOneLastNameMax)
                        .optional(),
                    email: zod.email().max(propertyDefinitionsListResponseResultsItemUpdatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                }),
                is_seen_on_filtered_events: zod.boolean().nullable(),
                property_type: zod
                    .union([
                        zod
                            .enum(['DateTime', 'String', 'Numeric', 'Boolean', 'Duration'])
                            .describe(
                                '* `DateTime` - DateTime\n* `String` - String\n* `Numeric` - Numeric\n* `Boolean` - Boolean\n* `Duration` - Duration'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
                verified: zod.boolean().optional(),
                verified_at: zod.iso.datetime({}).nullable(),
                verified_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(propertyDefinitionsListResponseResultsItemVerifiedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(propertyDefinitionsListResponseResultsItemVerifiedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(propertyDefinitionsListResponseResultsItemVerifiedByOneLastNameMax)
                        .optional(),
                    email: zod.email().max(propertyDefinitionsListResponseResultsItemVerifiedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                }),
                hidden: zod.boolean().nullish(),
            })
            .describe('Serializer mixin that handles tags for objects.')
    ),
})

export const propertyDefinitionsRetrieveResponseUpdatedByOneDistinctIdMax = 200

export const propertyDefinitionsRetrieveResponseUpdatedByOneFirstNameMax = 150

export const propertyDefinitionsRetrieveResponseUpdatedByOneLastNameMax = 150

export const propertyDefinitionsRetrieveResponseUpdatedByOneEmailMax = 254

export const propertyDefinitionsRetrieveResponseVerifiedByOneDistinctIdMax = 200

export const propertyDefinitionsRetrieveResponseVerifiedByOneFirstNameMax = 150

export const propertyDefinitionsRetrieveResponseVerifiedByOneLastNameMax = 150

export const propertyDefinitionsRetrieveResponseVerifiedByOneEmailMax = 254

export const PropertyDefinitionsRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        is_numerical: zod.boolean(),
        updated_at: zod.iso.datetime({}),
        updated_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(propertyDefinitionsRetrieveResponseUpdatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(propertyDefinitionsRetrieveResponseUpdatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(propertyDefinitionsRetrieveResponseUpdatedByOneLastNameMax).optional(),
            email: zod.email().max(propertyDefinitionsRetrieveResponseUpdatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        is_seen_on_filtered_events: zod.boolean().nullable(),
        property_type: zod
            .union([
                zod
                    .enum(['DateTime', 'String', 'Numeric', 'Boolean', 'Duration'])
                    .describe(
                        '* `DateTime` - DateTime\n* `String` - String\n* `Numeric` - Numeric\n* `Boolean` - Boolean\n* `Duration` - Duration'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
        verified: zod.boolean().optional(),
        verified_at: zod.iso.datetime({}).nullable(),
        verified_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(propertyDefinitionsRetrieveResponseVerifiedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(propertyDefinitionsRetrieveResponseVerifiedByOneFirstNameMax).optional(),
            last_name: zod.string().max(propertyDefinitionsRetrieveResponseVerifiedByOneLastNameMax).optional(),
            email: zod.email().max(propertyDefinitionsRetrieveResponseVerifiedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        hidden: zod.boolean().nullish(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const PropertyDefinitionsUpdateBody = /* @__PURE__ */ zod
    .object({
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        property_type: zod
            .union([
                zod
                    .enum(['DateTime', 'String', 'Numeric', 'Boolean', 'Duration'])
                    .describe(
                        '* `DateTime` - DateTime\n* `String` - String\n* `Numeric` - Numeric\n* `Boolean` - Boolean\n* `Duration` - Duration'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
        verified: zod.boolean().optional(),
        hidden: zod.boolean().nullish(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const propertyDefinitionsUpdateResponseUpdatedByOneDistinctIdMax = 200

export const propertyDefinitionsUpdateResponseUpdatedByOneFirstNameMax = 150

export const propertyDefinitionsUpdateResponseUpdatedByOneLastNameMax = 150

export const propertyDefinitionsUpdateResponseUpdatedByOneEmailMax = 254

export const propertyDefinitionsUpdateResponseVerifiedByOneDistinctIdMax = 200

export const propertyDefinitionsUpdateResponseVerifiedByOneFirstNameMax = 150

export const propertyDefinitionsUpdateResponseVerifiedByOneLastNameMax = 150

export const propertyDefinitionsUpdateResponseVerifiedByOneEmailMax = 254

export const PropertyDefinitionsUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        is_numerical: zod.boolean(),
        updated_at: zod.iso.datetime({}),
        updated_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(propertyDefinitionsUpdateResponseUpdatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(propertyDefinitionsUpdateResponseUpdatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(propertyDefinitionsUpdateResponseUpdatedByOneLastNameMax).optional(),
            email: zod.email().max(propertyDefinitionsUpdateResponseUpdatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        is_seen_on_filtered_events: zod.boolean().nullable(),
        property_type: zod
            .union([
                zod
                    .enum(['DateTime', 'String', 'Numeric', 'Boolean', 'Duration'])
                    .describe(
                        '* `DateTime` - DateTime\n* `String` - String\n* `Numeric` - Numeric\n* `Boolean` - Boolean\n* `Duration` - Duration'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
        verified: zod.boolean().optional(),
        verified_at: zod.iso.datetime({}).nullable(),
        verified_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(propertyDefinitionsUpdateResponseVerifiedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(propertyDefinitionsUpdateResponseVerifiedByOneFirstNameMax).optional(),
            last_name: zod.string().max(propertyDefinitionsUpdateResponseVerifiedByOneLastNameMax).optional(),
            email: zod.email().max(propertyDefinitionsUpdateResponseVerifiedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
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
                        '* `DateTime` - DateTime\n* `String` - String\n* `Numeric` - Numeric\n* `Boolean` - Boolean\n* `Duration` - Duration'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
        verified: zod.boolean().optional(),
        hidden: zod.boolean().nullish(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const propertyDefinitionsPartialUpdateResponseUpdatedByOneDistinctIdMax = 200

export const propertyDefinitionsPartialUpdateResponseUpdatedByOneFirstNameMax = 150

export const propertyDefinitionsPartialUpdateResponseUpdatedByOneLastNameMax = 150

export const propertyDefinitionsPartialUpdateResponseUpdatedByOneEmailMax = 254

export const propertyDefinitionsPartialUpdateResponseVerifiedByOneDistinctIdMax = 200

export const propertyDefinitionsPartialUpdateResponseVerifiedByOneFirstNameMax = 150

export const propertyDefinitionsPartialUpdateResponseVerifiedByOneLastNameMax = 150

export const propertyDefinitionsPartialUpdateResponseVerifiedByOneEmailMax = 254

export const PropertyDefinitionsPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        is_numerical: zod.boolean(),
        updated_at: zod.iso.datetime({}),
        updated_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(propertyDefinitionsPartialUpdateResponseUpdatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(propertyDefinitionsPartialUpdateResponseUpdatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(propertyDefinitionsPartialUpdateResponseUpdatedByOneLastNameMax).optional(),
            email: zod.email().max(propertyDefinitionsPartialUpdateResponseUpdatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        is_seen_on_filtered_events: zod.boolean().nullable(),
        property_type: zod
            .union([
                zod
                    .enum(['DateTime', 'String', 'Numeric', 'Boolean', 'Duration'])
                    .describe(
                        '* `DateTime` - DateTime\n* `String` - String\n* `Numeric` - Numeric\n* `Boolean` - Boolean\n* `Duration` - Duration'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
        verified: zod.boolean().optional(),
        verified_at: zod.iso.datetime({}).nullable(),
        verified_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(propertyDefinitionsPartialUpdateResponseVerifiedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(propertyDefinitionsPartialUpdateResponseVerifiedByOneFirstNameMax).optional(),
            last_name: zod.string().max(propertyDefinitionsPartialUpdateResponseVerifiedByOneLastNameMax).optional(),
            email: zod.email().max(propertyDefinitionsPartialUpdateResponseVerifiedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        hidden: zod.boolean().nullish(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const sessionRecordingsSharingListResponseSharePasswordsItemNoteMax = 100

export const SessionRecordingsSharingListResponseItem = /* @__PURE__ */ zod.object({
    created_at: zod.iso.datetime({}),
    enabled: zod.boolean().optional(),
    access_token: zod.string().nullable(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
    share_passwords: zod.array(
        zod.object({
            id: zod.number(),
            created_at: zod.iso.datetime({}),
            note: zod.string().max(sessionRecordingsSharingListResponseSharePasswordsItemNoteMax).nullish(),
            created_by_email: zod.string(),
            is_active: zod.boolean(),
        })
    ),
})
export const SessionRecordingsSharingListResponse = /* @__PURE__ */ zod.array(SessionRecordingsSharingListResponseItem)

/**
 * Create a new password for the sharing configuration.
 */
export const SessionRecordingsSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const sessionRecordingsSharingPasswordsCreateResponseSharePasswordsItemNoteMax = 100

export const SessionRecordingsSharingPasswordsCreateResponse = /* @__PURE__ */ zod.object({
    created_at: zod.iso.datetime({}),
    enabled: zod.boolean().optional(),
    access_token: zod.string().nullable(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
    share_passwords: zod.array(
        zod.object({
            id: zod.number(),
            created_at: zod.iso.datetime({}),
            note: zod.string().max(sessionRecordingsSharingPasswordsCreateResponseSharePasswordsItemNoteMax).nullish(),
            created_by_email: zod.string(),
            is_active: zod.boolean(),
        })
    ),
})

export const SessionRecordingsSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const sessionRecordingsSharingRefreshCreateResponseSharePasswordsItemNoteMax = 100

export const SessionRecordingsSharingRefreshCreateResponse = /* @__PURE__ */ zod.object({
    created_at: zod.iso.datetime({}),
    enabled: zod.boolean().optional(),
    access_token: zod.string().nullable(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
    share_passwords: zod.array(
        zod.object({
            id: zod.number(),
            created_at: zod.iso.datetime({}),
            note: zod.string().max(sessionRecordingsSharingRefreshCreateResponseSharePasswordsItemNoteMax).nullish(),
            created_by_email: zod.string(),
            is_active: zod.boolean(),
        })
    ),
})

export const subscriptionsListResponseResultsItemIntervalMin = -2147483648
export const subscriptionsListResponseResultsItemIntervalMax = 2147483647

export const subscriptionsListResponseResultsItemBysetposMin = -2147483648
export const subscriptionsListResponseResultsItemBysetposMax = 2147483647

export const subscriptionsListResponseResultsItemCountMin = -2147483648
export const subscriptionsListResponseResultsItemCountMax = 2147483647

export const subscriptionsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const subscriptionsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const subscriptionsListResponseResultsItemCreatedByOneLastNameMax = 150

export const subscriptionsListResponseResultsItemCreatedByOneEmailMax = 254

export const subscriptionsListResponseResultsItemTitleMax = 100

export const SubscriptionsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.number(),
                dashboard: zod.number().nullish(),
                insight: zod.number().nullish(),
                insight_short_id: zod.string().nullable(),
                resource_name: zod.string().nullable(),
                dashboard_export_insights: zod.array(zod.number()).optional(),
                target_type: zod
                    .enum(['email', 'slack', 'webhook'])
                    .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'),
                target_value: zod.string(),
                frequency: zod
                    .enum(['daily', 'weekly', 'monthly', 'yearly'])
                    .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'),
                interval: zod
                    .number()
                    .min(subscriptionsListResponseResultsItemIntervalMin)
                    .max(subscriptionsListResponseResultsItemIntervalMax)
                    .optional(),
                byweekday: zod
                    .array(
                        zod
                            .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                            .describe(
                                '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                            )
                    )
                    .nullish(),
                bysetpos: zod
                    .number()
                    .min(subscriptionsListResponseResultsItemBysetposMin)
                    .max(subscriptionsListResponseResultsItemBysetposMax)
                    .nullish(),
                count: zod
                    .number()
                    .min(subscriptionsListResponseResultsItemCountMin)
                    .max(subscriptionsListResponseResultsItemCountMax)
                    .nullish(),
                start_date: zod.iso.datetime({}),
                until_date: zod.iso.datetime({}).nullish(),
                created_at: zod.iso.datetime({}),
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(subscriptionsListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(subscriptionsListResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod.string().max(subscriptionsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                    email: zod.email().max(subscriptionsListResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                }),
                deleted: zod.boolean().optional(),
                title: zod.string().max(subscriptionsListResponseResultsItemTitleMax).nullish(),
                summary: zod.string(),
                next_delivery_date: zod.iso.datetime({}).nullable(),
                integration_id: zod.number().nullish(),
                invite_message: zod.string().nullish(),
            })
            .describe('Standard Subscription serializer.')
    ),
})

export const subscriptionsCreateBodyIntervalMin = -2147483648
export const subscriptionsCreateBodyIntervalMax = 2147483647

export const subscriptionsCreateBodyBysetposMin = -2147483648
export const subscriptionsCreateBodyBysetposMax = 2147483647

export const subscriptionsCreateBodyCountMin = -2147483648
export const subscriptionsCreateBodyCountMax = 2147483647

export const subscriptionsCreateBodyTitleMax = 100

export const SubscriptionsCreateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod.number().nullish(),
        insight: zod.number().nullish(),
        dashboard_export_insights: zod.array(zod.number()).optional(),
        target_type: zod
            .enum(['email', 'slack', 'webhook'])
            .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'),
        target_value: zod.string(),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'),
        interval: zod
            .number()
            .min(subscriptionsCreateBodyIntervalMin)
            .max(subscriptionsCreateBodyIntervalMax)
            .optional(),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish(),
        bysetpos: zod
            .number()
            .min(subscriptionsCreateBodyBysetposMin)
            .max(subscriptionsCreateBodyBysetposMax)
            .nullish(),
        count: zod.number().min(subscriptionsCreateBodyCountMin).max(subscriptionsCreateBodyCountMax).nullish(),
        start_date: zod.iso.datetime({}),
        until_date: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        title: zod.string().max(subscriptionsCreateBodyTitleMax).nullish(),
        integration_id: zod.number().nullish(),
        invite_message: zod.string().nullish(),
    })
    .describe('Standard Subscription serializer.')

export const subscriptionsRetrieveResponseIntervalMin = -2147483648
export const subscriptionsRetrieveResponseIntervalMax = 2147483647

export const subscriptionsRetrieveResponseBysetposMin = -2147483648
export const subscriptionsRetrieveResponseBysetposMax = 2147483647

export const subscriptionsRetrieveResponseCountMin = -2147483648
export const subscriptionsRetrieveResponseCountMax = 2147483647

export const subscriptionsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const subscriptionsRetrieveResponseCreatedByOneFirstNameMax = 150

export const subscriptionsRetrieveResponseCreatedByOneLastNameMax = 150

export const subscriptionsRetrieveResponseCreatedByOneEmailMax = 254

export const subscriptionsRetrieveResponseTitleMax = 100

export const SubscriptionsRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        dashboard: zod.number().nullish(),
        insight: zod.number().nullish(),
        insight_short_id: zod.string().nullable(),
        resource_name: zod.string().nullable(),
        dashboard_export_insights: zod.array(zod.number()).optional(),
        target_type: zod
            .enum(['email', 'slack', 'webhook'])
            .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'),
        target_value: zod.string(),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'),
        interval: zod
            .number()
            .min(subscriptionsRetrieveResponseIntervalMin)
            .max(subscriptionsRetrieveResponseIntervalMax)
            .optional(),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish(),
        bysetpos: zod
            .number()
            .min(subscriptionsRetrieveResponseBysetposMin)
            .max(subscriptionsRetrieveResponseBysetposMax)
            .nullish(),
        count: zod
            .number()
            .min(subscriptionsRetrieveResponseCountMin)
            .max(subscriptionsRetrieveResponseCountMax)
            .nullish(),
        start_date: zod.iso.datetime({}),
        until_date: zod.iso.datetime({}).nullish(),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(subscriptionsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(subscriptionsRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(subscriptionsRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(subscriptionsRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        deleted: zod.boolean().optional(),
        title: zod.string().max(subscriptionsRetrieveResponseTitleMax).nullish(),
        summary: zod.string(),
        next_delivery_date: zod.iso.datetime({}).nullable(),
        integration_id: zod.number().nullish(),
        invite_message: zod.string().nullish(),
    })
    .describe('Standard Subscription serializer.')

export const subscriptionsUpdateBodyIntervalMin = -2147483648
export const subscriptionsUpdateBodyIntervalMax = 2147483647

export const subscriptionsUpdateBodyBysetposMin = -2147483648
export const subscriptionsUpdateBodyBysetposMax = 2147483647

export const subscriptionsUpdateBodyCountMin = -2147483648
export const subscriptionsUpdateBodyCountMax = 2147483647

export const subscriptionsUpdateBodyTitleMax = 100

export const SubscriptionsUpdateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod.number().nullish(),
        insight: zod.number().nullish(),
        dashboard_export_insights: zod.array(zod.number()).optional(),
        target_type: zod
            .enum(['email', 'slack', 'webhook'])
            .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'),
        target_value: zod.string(),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'),
        interval: zod
            .number()
            .min(subscriptionsUpdateBodyIntervalMin)
            .max(subscriptionsUpdateBodyIntervalMax)
            .optional(),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish(),
        bysetpos: zod
            .number()
            .min(subscriptionsUpdateBodyBysetposMin)
            .max(subscriptionsUpdateBodyBysetposMax)
            .nullish(),
        count: zod.number().min(subscriptionsUpdateBodyCountMin).max(subscriptionsUpdateBodyCountMax).nullish(),
        start_date: zod.iso.datetime({}),
        until_date: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        title: zod.string().max(subscriptionsUpdateBodyTitleMax).nullish(),
        integration_id: zod.number().nullish(),
        invite_message: zod.string().nullish(),
    })
    .describe('Standard Subscription serializer.')

export const subscriptionsUpdateResponseIntervalMin = -2147483648
export const subscriptionsUpdateResponseIntervalMax = 2147483647

export const subscriptionsUpdateResponseBysetposMin = -2147483648
export const subscriptionsUpdateResponseBysetposMax = 2147483647

export const subscriptionsUpdateResponseCountMin = -2147483648
export const subscriptionsUpdateResponseCountMax = 2147483647

export const subscriptionsUpdateResponseCreatedByOneDistinctIdMax = 200

export const subscriptionsUpdateResponseCreatedByOneFirstNameMax = 150

export const subscriptionsUpdateResponseCreatedByOneLastNameMax = 150

export const subscriptionsUpdateResponseCreatedByOneEmailMax = 254

export const subscriptionsUpdateResponseTitleMax = 100

export const SubscriptionsUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        dashboard: zod.number().nullish(),
        insight: zod.number().nullish(),
        insight_short_id: zod.string().nullable(),
        resource_name: zod.string().nullable(),
        dashboard_export_insights: zod.array(zod.number()).optional(),
        target_type: zod
            .enum(['email', 'slack', 'webhook'])
            .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'),
        target_value: zod.string(),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'),
        interval: zod
            .number()
            .min(subscriptionsUpdateResponseIntervalMin)
            .max(subscriptionsUpdateResponseIntervalMax)
            .optional(),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish(),
        bysetpos: zod
            .number()
            .min(subscriptionsUpdateResponseBysetposMin)
            .max(subscriptionsUpdateResponseBysetposMax)
            .nullish(),
        count: zod.number().min(subscriptionsUpdateResponseCountMin).max(subscriptionsUpdateResponseCountMax).nullish(),
        start_date: zod.iso.datetime({}),
        until_date: zod.iso.datetime({}).nullish(),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(subscriptionsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(subscriptionsUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(subscriptionsUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(subscriptionsUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        deleted: zod.boolean().optional(),
        title: zod.string().max(subscriptionsUpdateResponseTitleMax).nullish(),
        summary: zod.string(),
        next_delivery_date: zod.iso.datetime({}).nullable(),
        integration_id: zod.number().nullish(),
        invite_message: zod.string().nullish(),
    })
    .describe('Standard Subscription serializer.')

export const subscriptionsPartialUpdateBodyIntervalMin = -2147483648
export const subscriptionsPartialUpdateBodyIntervalMax = 2147483647

export const subscriptionsPartialUpdateBodyBysetposMin = -2147483648
export const subscriptionsPartialUpdateBodyBysetposMax = 2147483647

export const subscriptionsPartialUpdateBodyCountMin = -2147483648
export const subscriptionsPartialUpdateBodyCountMax = 2147483647

export const subscriptionsPartialUpdateBodyTitleMax = 100

export const SubscriptionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod.number().nullish(),
        insight: zod.number().nullish(),
        dashboard_export_insights: zod.array(zod.number()).optional(),
        target_type: zod
            .enum(['email', 'slack', 'webhook'])
            .optional()
            .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'),
        target_value: zod.string().optional(),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .optional()
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'),
        interval: zod
            .number()
            .min(subscriptionsPartialUpdateBodyIntervalMin)
            .max(subscriptionsPartialUpdateBodyIntervalMax)
            .optional(),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish(),
        bysetpos: zod
            .number()
            .min(subscriptionsPartialUpdateBodyBysetposMin)
            .max(subscriptionsPartialUpdateBodyBysetposMax)
            .nullish(),
        count: zod
            .number()
            .min(subscriptionsPartialUpdateBodyCountMin)
            .max(subscriptionsPartialUpdateBodyCountMax)
            .nullish(),
        start_date: zod.iso.datetime({}).optional(),
        until_date: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        title: zod.string().max(subscriptionsPartialUpdateBodyTitleMax).nullish(),
        integration_id: zod.number().nullish(),
        invite_message: zod.string().nullish(),
    })
    .describe('Standard Subscription serializer.')

export const subscriptionsPartialUpdateResponseIntervalMin = -2147483648
export const subscriptionsPartialUpdateResponseIntervalMax = 2147483647

export const subscriptionsPartialUpdateResponseBysetposMin = -2147483648
export const subscriptionsPartialUpdateResponseBysetposMax = 2147483647

export const subscriptionsPartialUpdateResponseCountMin = -2147483648
export const subscriptionsPartialUpdateResponseCountMax = 2147483647

export const subscriptionsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const subscriptionsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const subscriptionsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const subscriptionsPartialUpdateResponseCreatedByOneEmailMax = 254

export const subscriptionsPartialUpdateResponseTitleMax = 100

export const SubscriptionsPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        dashboard: zod.number().nullish(),
        insight: zod.number().nullish(),
        insight_short_id: zod.string().nullable(),
        resource_name: zod.string().nullable(),
        dashboard_export_insights: zod.array(zod.number()).optional(),
        target_type: zod
            .enum(['email', 'slack', 'webhook'])
            .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'),
        target_value: zod.string(),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'),
        interval: zod
            .number()
            .min(subscriptionsPartialUpdateResponseIntervalMin)
            .max(subscriptionsPartialUpdateResponseIntervalMax)
            .optional(),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish(),
        bysetpos: zod
            .number()
            .min(subscriptionsPartialUpdateResponseBysetposMin)
            .max(subscriptionsPartialUpdateResponseBysetposMax)
            .nullish(),
        count: zod
            .number()
            .min(subscriptionsPartialUpdateResponseCountMin)
            .max(subscriptionsPartialUpdateResponseCountMax)
            .nullish(),
        start_date: zod.iso.datetime({}),
        until_date: zod.iso.datetime({}).nullish(),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(subscriptionsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(subscriptionsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(subscriptionsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(subscriptionsPartialUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        deleted: zod.boolean().optional(),
        title: zod.string().max(subscriptionsPartialUpdateResponseTitleMax).nullish(),
        summary: zod.string(),
        next_delivery_date: zod.iso.datetime({}).nullable(),
        integration_id: zod.number().nullish(),
        invite_message: zod.string().nullish(),
    })
    .describe('Standard Subscription serializer.')

export const usersListResponseResultsItemFirstNameMax = 150

export const usersListResponseResultsItemLastNameMax = 150

export const usersListResponseResultsItemEmailMax = 254

export const usersListResponseResultsItemTeamOneProjectIdMin = -9223372036854776000
export const usersListResponseResultsItemTeamOneProjectIdMax = 9223372036854776000

export const usersListResponseResultsItemOrganizationOneNameMax = 64

export const usersListResponseResultsItemOrganizationOneSlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const usersListResponseResultsItemOrganizationsItemNameMax = 64

export const usersListResponseResultsItemOrganizationsItemSlugMax = 48

export const usersListResponseResultsItemOrganizationsItemSlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const usersListResponseResultsItemOrganizationsItemIsNotActiveReasonMax = 200

export const usersListResponseResultsItemPasswordMax = 128

export const usersListResponseResultsItemScenePersonalisationItemSceneMax = 200

export const UsersListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            date_joined: zod.iso.datetime({}),
            uuid: zod.uuid(),
            distinct_id: zod.string().nullable(),
            first_name: zod.string().max(usersListResponseResultsItemFirstNameMax).optional(),
            last_name: zod.string().max(usersListResponseResultsItemLastNameMax).optional(),
            email: zod.email().max(usersListResponseResultsItemEmailMax),
            pending_email: zod.email().nullable(),
            is_email_verified: zod.boolean().nullable(),
            notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
            anonymize_data: zod.boolean().nullish(),
            allow_impersonation: zod.boolean().nullish(),
            toolbar_mode: zod
                .union([
                    zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
            has_password: zod.boolean(),
            id: zod.number(),
            is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
            is_impersonated: zod.boolean().nullable(),
            is_impersonated_until: zod.string().nullable(),
            is_impersonated_read_only: zod.boolean().nullable(),
            sensitive_session_expires_at: zod.string().nullable(),
            team: zod
                .object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    organization: zod.uuid(),
                    project_id: zod
                        .number()
                        .min(usersListResponseResultsItemTeamOneProjectIdMin)
                        .max(usersListResponseResultsItemTeamOneProjectIdMax),
                    api_token: zod.string(),
                    name: zod.string(),
                    completed_snippet_onboarding: zod.boolean(),
                    has_completed_onboarding_for: zod.unknown().nullable(),
                    ingested_event: zod.boolean(),
                    is_demo: zod.boolean(),
                    timezone: zod.string(),
                    access_control: zod.boolean(),
                })
                .describe(
                    'Serializer for `Team` model with minimal attributes to speeed up loading and transfer times.\nAlso used for nested serializers.'
                ),
            organization: zod.object({
                id: zod.uuid(),
                name: zod.string().max(usersListResponseResultsItemOrganizationOneNameMax),
                slug: zod.string().regex(usersListResponseResultsItemOrganizationOneSlugRegExp),
                logo_media_id: zod.uuid().nullish(),
                created_at: zod.iso.datetime({}),
                updated_at: zod.iso.datetime({}),
                membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
                plugins_access_level: zod
                    .union([zod.literal(0), zod.literal(3), zod.literal(6), zod.literal(9)])
                    .describe('* `0` - none\n* `3` - config\n* `6` - install\n* `9` - root'),
                teams: zod.array(zod.record(zod.string(), zod.unknown())),
                projects: zod.array(zod.record(zod.string(), zod.unknown())),
                available_product_features: zod.array(zod.unknown()).nullable(),
                is_member_join_email_enabled: zod
                    .boolean()
                    .describe(
                        'Legacy field; member-join emails are controlled per user in account notification settings.'
                    ),
                metadata: zod.record(zod.string(), zod.string()),
                customer_id: zod.string().nullable(),
                enforce_2fa: zod.boolean().nullish(),
                members_can_invite: zod.boolean().nullish(),
                members_can_use_personal_api_keys: zod.boolean().optional(),
                allow_publicly_shared_resources: zod.boolean().optional(),
                member_count: zod.number(),
                is_ai_data_processing_approved: zod.boolean().nullish(),
                default_experiment_stats_method: zod
                    .union([
                        zod
                            .enum(['bayesian', 'frequentist'])
                            .describe('* `bayesian` - Bayesian\n* `frequentist` - Frequentist'),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish()
                    .describe(
                        'Default statistical method for new experiments in this organization.\n\n* `bayesian` - Bayesian\n* `frequentist` - Frequentist'
                    ),
                default_anonymize_ips: zod
                    .boolean()
                    .optional()
                    .describe("Default setting for 'Discard client IP data' for new projects in this organization."),
                default_role_id: zod
                    .string()
                    .nullish()
                    .describe('ID of the role to automatically assign to new members joining the organization'),
                is_active: zod
                    .boolean()
                    .nullable()
                    .describe("Set this to 'No' to temporarily disable an organization."),
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
            }),
            organizations: zod.array(
                zod
                    .object({
                        id: zod.uuid(),
                        name: zod.string().max(usersListResponseResultsItemOrganizationsItemNameMax),
                        slug: zod
                            .string()
                            .max(usersListResponseResultsItemOrganizationsItemSlugMax)
                            .regex(usersListResponseResultsItemOrganizationsItemSlugRegExp),
                        logo_media_id: zod.uuid().nullable(),
                        membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
                        members_can_use_personal_api_keys: zod.boolean().optional(),
                        is_active: zod
                            .boolean()
                            .nullish()
                            .describe("Set this to 'No' to temporarily disable an organization."),
                        is_not_active_reason: zod
                            .string()
                            .max(usersListResponseResultsItemOrganizationsItemIsNotActiveReasonMax)
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
            ),
            set_current_organization: zod.string().optional(),
            set_current_team: zod.string().optional(),
            password: zod.string().max(usersListResponseResultsItemPasswordMax),
            current_password: zod.string().optional(),
            events_column_config: zod.unknown().optional(),
            is_2fa_enabled: zod.boolean(),
            has_social_auth: zod.boolean(),
            has_sso_enforcement: zod.boolean(),
            has_seen_product_intro_for: zod.unknown().nullish(),
            scene_personalisation: zod.array(
                zod.object({
                    scene: zod.string().max(usersListResponseResultsItemScenePersonalisationItemSceneMax),
                    dashboard: zod.number().nullish(),
                })
            ),
            theme_mode: zod
                .union([
                    zod
                        .enum(['light', 'dark', 'system'])
                        .describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
            hedgehog_config: zod.unknown().nullish(),
            allow_sidebar_suggestions: zod.boolean().nullish(),
            shortcut_position: zod
                .union([
                    zod
                        .enum(['above', 'below', 'hidden'])
                        .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
            role_at_organization: zod
                .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                .optional()
                .describe(
                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                ),
            passkeys_enabled_for_2fa: zod
                .boolean()
                .nullish()
                .describe(
                    'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
                ),
        })
    ),
})

export const usersRetrieveResponseFirstNameMax = 150

export const usersRetrieveResponseLastNameMax = 150

export const usersRetrieveResponseEmailMax = 254

export const usersRetrieveResponseTeamOneProjectIdMin = -9223372036854776000
export const usersRetrieveResponseTeamOneProjectIdMax = 9223372036854776000

export const usersRetrieveResponseOrganizationOneNameMax = 64

export const usersRetrieveResponseOrganizationOneSlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const usersRetrieveResponseOrganizationsItemNameMax = 64

export const usersRetrieveResponseOrganizationsItemSlugMax = 48

export const usersRetrieveResponseOrganizationsItemSlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const usersRetrieveResponseOrganizationsItemIsNotActiveReasonMax = 200

export const usersRetrieveResponsePasswordMax = 128

export const usersRetrieveResponseScenePersonalisationItemSceneMax = 200

export const UsersRetrieveResponse = /* @__PURE__ */ zod.object({
    date_joined: zod.iso.datetime({}),
    uuid: zod.uuid(),
    distinct_id: zod.string().nullable(),
    first_name: zod.string().max(usersRetrieveResponseFirstNameMax).optional(),
    last_name: zod.string().max(usersRetrieveResponseLastNameMax).optional(),
    email: zod.email().max(usersRetrieveResponseEmailMax),
    pending_email: zod.email().nullable(),
    is_email_verified: zod.boolean().nullable(),
    notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
    anonymize_data: zod.boolean().nullish(),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    has_password: zod.boolean(),
    id: zod.number(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    is_impersonated: zod.boolean().nullable(),
    is_impersonated_until: zod.string().nullable(),
    is_impersonated_read_only: zod.boolean().nullable(),
    sensitive_session_expires_at: zod.string().nullable(),
    team: zod
        .object({
            id: zod.number(),
            uuid: zod.uuid(),
            organization: zod.uuid(),
            project_id: zod
                .number()
                .min(usersRetrieveResponseTeamOneProjectIdMin)
                .max(usersRetrieveResponseTeamOneProjectIdMax),
            api_token: zod.string(),
            name: zod.string(),
            completed_snippet_onboarding: zod.boolean(),
            has_completed_onboarding_for: zod.unknown().nullable(),
            ingested_event: zod.boolean(),
            is_demo: zod.boolean(),
            timezone: zod.string(),
            access_control: zod.boolean(),
        })
        .describe(
            'Serializer for `Team` model with minimal attributes to speeed up loading and transfer times.\nAlso used for nested serializers.'
        ),
    organization: zod.object({
        id: zod.uuid(),
        name: zod.string().max(usersRetrieveResponseOrganizationOneNameMax),
        slug: zod.string().regex(usersRetrieveResponseOrganizationOneSlugRegExp),
        logo_media_id: zod.uuid().nullish(),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        plugins_access_level: zod
            .union([zod.literal(0), zod.literal(3), zod.literal(6), zod.literal(9)])
            .describe('* `0` - none\n* `3` - config\n* `6` - install\n* `9` - root'),
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
        members_can_use_personal_api_keys: zod.boolean().optional(),
        allow_publicly_shared_resources: zod.boolean().optional(),
        member_count: zod.number(),
        is_ai_data_processing_approved: zod.boolean().nullish(),
        default_experiment_stats_method: zod
            .union([
                zod
                    .enum(['bayesian', 'frequentist'])
                    .describe('* `bayesian` - Bayesian\n* `frequentist` - Frequentist'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Default statistical method for new experiments in this organization.\n\n* `bayesian` - Bayesian\n* `frequentist` - Frequentist'
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
    }),
    organizations: zod.array(
        zod
            .object({
                id: zod.uuid(),
                name: zod.string().max(usersRetrieveResponseOrganizationsItemNameMax),
                slug: zod
                    .string()
                    .max(usersRetrieveResponseOrganizationsItemSlugMax)
                    .regex(usersRetrieveResponseOrganizationsItemSlugRegExp),
                logo_media_id: zod.uuid().nullable(),
                membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
                members_can_use_personal_api_keys: zod.boolean().optional(),
                is_active: zod.boolean().nullish().describe("Set this to 'No' to temporarily disable an organization."),
                is_not_active_reason: zod
                    .string()
                    .max(usersRetrieveResponseOrganizationsItemIsNotActiveReasonMax)
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
    ),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersRetrieveResponsePasswordMax),
    current_password: zod.string().optional(),
    events_column_config: zod.unknown().optional(),
    is_2fa_enabled: zod.boolean(),
    has_social_auth: zod.boolean(),
    has_sso_enforcement: zod.boolean(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    scene_personalisation: zod.array(
        zod.object({
            scene: zod.string().max(usersRetrieveResponseScenePersonalisationItemSceneMax),
            dashboard: zod.number().nullish(),
        })
    ),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

export const usersUpdateBodyFirstNameMax = 150

export const usersUpdateBodyLastNameMax = 150

export const usersUpdateBodyEmailMax = 254

export const usersUpdateBodyPasswordMax = 128

export const UsersUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersUpdateBodyEmailMax),
    notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
    anonymize_data: zod.boolean().nullish(),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersUpdateBodyPasswordMax),
    current_password: zod.string().optional(),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

export const usersUpdateResponseFirstNameMax = 150

export const usersUpdateResponseLastNameMax = 150

export const usersUpdateResponseEmailMax = 254

export const usersUpdateResponseTeamOneProjectIdMin = -9223372036854776000
export const usersUpdateResponseTeamOneProjectIdMax = 9223372036854776000

export const usersUpdateResponseOrganizationOneNameMax = 64

export const usersUpdateResponseOrganizationOneSlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const usersUpdateResponseOrganizationsItemNameMax = 64

export const usersUpdateResponseOrganizationsItemSlugMax = 48

export const usersUpdateResponseOrganizationsItemSlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const usersUpdateResponseOrganizationsItemIsNotActiveReasonMax = 200

export const usersUpdateResponsePasswordMax = 128

export const usersUpdateResponseScenePersonalisationItemSceneMax = 200

export const UsersUpdateResponse = /* @__PURE__ */ zod.object({
    date_joined: zod.iso.datetime({}),
    uuid: zod.uuid(),
    distinct_id: zod.string().nullable(),
    first_name: zod.string().max(usersUpdateResponseFirstNameMax).optional(),
    last_name: zod.string().max(usersUpdateResponseLastNameMax).optional(),
    email: zod.email().max(usersUpdateResponseEmailMax),
    pending_email: zod.email().nullable(),
    is_email_verified: zod.boolean().nullable(),
    notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
    anonymize_data: zod.boolean().nullish(),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    has_password: zod.boolean(),
    id: zod.number(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    is_impersonated: zod.boolean().nullable(),
    is_impersonated_until: zod.string().nullable(),
    is_impersonated_read_only: zod.boolean().nullable(),
    sensitive_session_expires_at: zod.string().nullable(),
    team: zod
        .object({
            id: zod.number(),
            uuid: zod.uuid(),
            organization: zod.uuid(),
            project_id: zod
                .number()
                .min(usersUpdateResponseTeamOneProjectIdMin)
                .max(usersUpdateResponseTeamOneProjectIdMax),
            api_token: zod.string(),
            name: zod.string(),
            completed_snippet_onboarding: zod.boolean(),
            has_completed_onboarding_for: zod.unknown().nullable(),
            ingested_event: zod.boolean(),
            is_demo: zod.boolean(),
            timezone: zod.string(),
            access_control: zod.boolean(),
        })
        .describe(
            'Serializer for `Team` model with minimal attributes to speeed up loading and transfer times.\nAlso used for nested serializers.'
        ),
    organization: zod.object({
        id: zod.uuid(),
        name: zod.string().max(usersUpdateResponseOrganizationOneNameMax),
        slug: zod.string().regex(usersUpdateResponseOrganizationOneSlugRegExp),
        logo_media_id: zod.uuid().nullish(),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        plugins_access_level: zod
            .union([zod.literal(0), zod.literal(3), zod.literal(6), zod.literal(9)])
            .describe('* `0` - none\n* `3` - config\n* `6` - install\n* `9` - root'),
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
        members_can_use_personal_api_keys: zod.boolean().optional(),
        allow_publicly_shared_resources: zod.boolean().optional(),
        member_count: zod.number(),
        is_ai_data_processing_approved: zod.boolean().nullish(),
        default_experiment_stats_method: zod
            .union([
                zod
                    .enum(['bayesian', 'frequentist'])
                    .describe('* `bayesian` - Bayesian\n* `frequentist` - Frequentist'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Default statistical method for new experiments in this organization.\n\n* `bayesian` - Bayesian\n* `frequentist` - Frequentist'
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
    }),
    organizations: zod.array(
        zod
            .object({
                id: zod.uuid(),
                name: zod.string().max(usersUpdateResponseOrganizationsItemNameMax),
                slug: zod
                    .string()
                    .max(usersUpdateResponseOrganizationsItemSlugMax)
                    .regex(usersUpdateResponseOrganizationsItemSlugRegExp),
                logo_media_id: zod.uuid().nullable(),
                membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
                members_can_use_personal_api_keys: zod.boolean().optional(),
                is_active: zod.boolean().nullish().describe("Set this to 'No' to temporarily disable an organization."),
                is_not_active_reason: zod
                    .string()
                    .max(usersUpdateResponseOrganizationsItemIsNotActiveReasonMax)
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
    ),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersUpdateResponsePasswordMax),
    current_password: zod.string().optional(),
    events_column_config: zod.unknown().optional(),
    is_2fa_enabled: zod.boolean(),
    has_social_auth: zod.boolean(),
    has_sso_enforcement: zod.boolean(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    scene_personalisation: zod.array(
        zod.object({
            scene: zod.string().max(usersUpdateResponseScenePersonalisationItemSceneMax),
            dashboard: zod.number().nullish(),
        })
    ),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

export const usersPartialUpdateBodyFirstNameMax = 150

export const usersPartialUpdateBodyLastNameMax = 150

export const usersPartialUpdateBodyEmailMax = 254

export const usersPartialUpdateBodyPasswordMax = 128

export const UsersPartialUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersPartialUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersPartialUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersPartialUpdateBodyEmailMax).optional(),
    notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
    anonymize_data: zod.boolean().nullish(),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersPartialUpdateBodyPasswordMax).optional(),
    current_password: zod.string().optional(),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

export const usersPartialUpdateResponseFirstNameMax = 150

export const usersPartialUpdateResponseLastNameMax = 150

export const usersPartialUpdateResponseEmailMax = 254

export const usersPartialUpdateResponseTeamOneProjectIdMin = -9223372036854776000
export const usersPartialUpdateResponseTeamOneProjectIdMax = 9223372036854776000

export const usersPartialUpdateResponseOrganizationOneNameMax = 64

export const usersPartialUpdateResponseOrganizationOneSlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const usersPartialUpdateResponseOrganizationsItemNameMax = 64

export const usersPartialUpdateResponseOrganizationsItemSlugMax = 48

export const usersPartialUpdateResponseOrganizationsItemSlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')
export const usersPartialUpdateResponseOrganizationsItemIsNotActiveReasonMax = 200

export const usersPartialUpdateResponsePasswordMax = 128

export const usersPartialUpdateResponseScenePersonalisationItemSceneMax = 200

export const UsersPartialUpdateResponse = /* @__PURE__ */ zod.object({
    date_joined: zod.iso.datetime({}),
    uuid: zod.uuid(),
    distinct_id: zod.string().nullable(),
    first_name: zod.string().max(usersPartialUpdateResponseFirstNameMax).optional(),
    last_name: zod.string().max(usersPartialUpdateResponseLastNameMax).optional(),
    email: zod.email().max(usersPartialUpdateResponseEmailMax),
    pending_email: zod.email().nullable(),
    is_email_verified: zod.boolean().nullable(),
    notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
    anonymize_data: zod.boolean().nullish(),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    has_password: zod.boolean(),
    id: zod.number(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    is_impersonated: zod.boolean().nullable(),
    is_impersonated_until: zod.string().nullable(),
    is_impersonated_read_only: zod.boolean().nullable(),
    sensitive_session_expires_at: zod.string().nullable(),
    team: zod
        .object({
            id: zod.number(),
            uuid: zod.uuid(),
            organization: zod.uuid(),
            project_id: zod
                .number()
                .min(usersPartialUpdateResponseTeamOneProjectIdMin)
                .max(usersPartialUpdateResponseTeamOneProjectIdMax),
            api_token: zod.string(),
            name: zod.string(),
            completed_snippet_onboarding: zod.boolean(),
            has_completed_onboarding_for: zod.unknown().nullable(),
            ingested_event: zod.boolean(),
            is_demo: zod.boolean(),
            timezone: zod.string(),
            access_control: zod.boolean(),
        })
        .describe(
            'Serializer for `Team` model with minimal attributes to speeed up loading and transfer times.\nAlso used for nested serializers.'
        ),
    organization: zod.object({
        id: zod.uuid(),
        name: zod.string().max(usersPartialUpdateResponseOrganizationOneNameMax),
        slug: zod.string().regex(usersPartialUpdateResponseOrganizationOneSlugRegExp),
        logo_media_id: zod.uuid().nullish(),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
        plugins_access_level: zod
            .union([zod.literal(0), zod.literal(3), zod.literal(6), zod.literal(9)])
            .describe('* `0` - none\n* `3` - config\n* `6` - install\n* `9` - root'),
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
        members_can_use_personal_api_keys: zod.boolean().optional(),
        allow_publicly_shared_resources: zod.boolean().optional(),
        member_count: zod.number(),
        is_ai_data_processing_approved: zod.boolean().nullish(),
        default_experiment_stats_method: zod
            .union([
                zod
                    .enum(['bayesian', 'frequentist'])
                    .describe('* `bayesian` - Bayesian\n* `frequentist` - Frequentist'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Default statistical method for new experiments in this organization.\n\n* `bayesian` - Bayesian\n* `frequentist` - Frequentist'
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
    }),
    organizations: zod.array(
        zod
            .object({
                id: zod.uuid(),
                name: zod.string().max(usersPartialUpdateResponseOrganizationsItemNameMax),
                slug: zod
                    .string()
                    .max(usersPartialUpdateResponseOrganizationsItemSlugMax)
                    .regex(usersPartialUpdateResponseOrganizationsItemSlugRegExp),
                logo_media_id: zod.uuid().nullable(),
                membership_level: zod.union([zod.literal(1), zod.literal(8), zod.literal(15)]).nullable(),
                members_can_use_personal_api_keys: zod.boolean().optional(),
                is_active: zod.boolean().nullish().describe("Set this to 'No' to temporarily disable an organization."),
                is_not_active_reason: zod
                    .string()
                    .max(usersPartialUpdateResponseOrganizationsItemIsNotActiveReasonMax)
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
    ),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersPartialUpdateResponsePasswordMax),
    current_password: zod.string().optional(),
    events_column_config: zod.unknown().optional(),
    is_2fa_enabled: zod.boolean(),
    has_social_auth: zod.boolean(),
    has_sso_enforcement: zod.boolean(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    scene_personalisation: zod.array(
        zod.object({
            scene: zod.string().max(usersPartialUpdateResponseScenePersonalisationItemSceneMax),
            dashboard: zod.number().nullish(),
        })
    ),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
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
    notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
    anonymize_data: zod.boolean().nullish(),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersHedgehogConfigPartialUpdateBodyPasswordMax).optional(),
    current_password: zod.string().optional(),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

export const usersScenePersonalisationCreateBodyFirstNameMax = 150

export const usersScenePersonalisationCreateBodyLastNameMax = 150

export const usersScenePersonalisationCreateBodyEmailMax = 254

export const usersScenePersonalisationCreateBodyPasswordMax = 128

export const UsersScenePersonalisationCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersScenePersonalisationCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersScenePersonalisationCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersScenePersonalisationCreateBodyEmailMax),
    notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
    anonymize_data: zod.boolean().nullish(),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersScenePersonalisationCreateBodyPasswordMax),
    current_password: zod.string().optional(),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
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
    notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
    anonymize_data: zod.boolean().nullish(),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersTwoFactorBackupCodesCreateBodyPasswordMax),
    current_password: zod.string().optional(),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
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
    notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
    anonymize_data: zod.boolean().nullish(),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersTwoFactorDisableCreateBodyPasswordMax),
    current_password: zod.string().optional(),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
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
    notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
    anonymize_data: zod.boolean().nullish(),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersTwoFactorValidateCreateBodyPasswordMax),
    current_password: zod.string().optional(),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
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
    notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
    anonymize_data: zod.boolean().nullish(),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersValidate2faCreateBodyPasswordMax),
    current_password: zod.string().optional(),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
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
    notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
    anonymize_data: zod.boolean().nullish(),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersCancelEmailChangeRequestPartialUpdateBodyPasswordMax).optional(),
    current_password: zod.string().optional(),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
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
    notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
    anonymize_data: zod.boolean().nullish(),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersRequestEmailVerificationCreateBodyPasswordMax),
    current_password: zod.string().optional(),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
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
    notification_settings: zod.record(zod.string(), zod.unknown()).optional(),
    anonymize_data: zod.boolean().nullish(),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersVerifyEmailCreateBodyPasswordMax),
    current_password: zod.string().optional(),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})
