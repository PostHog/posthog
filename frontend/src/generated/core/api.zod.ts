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
 * Projects for the current organization.
 */
export const create2BodyNameMax = 200

export const create2BodyProductDescriptionMax = 1000

export const create2BodyAppUrlsItemMax = 200

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
export const update2BodyNameMax = 200

export const update2BodyProductDescriptionMax = 1000

export const update2BodyAppUrlsItemMax = 200

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

/**
 * Projects for the current organization.
 */
export const partialUpdate2BodyNameMax = 200

export const partialUpdate2BodyProductDescriptionMax = 1000

export const partialUpdate2BodyAppUrlsItemMax = 200

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

/**
 * Projects for the current organization.
 */
export const addProductIntentPartialUpdateBodyNameMax = 200

export const addProductIntentPartialUpdateBodyProductDescriptionMax = 1000

export const addProductIntentPartialUpdateBodyAppUrlsItemMax = 200

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

/**
 * Projects for the current organization.
 */
export const changeOrganizationCreateBodyNameMax = 200

export const changeOrganizationCreateBodyProductDescriptionMax = 1000

export const changeOrganizationCreateBodyAppUrlsItemMax = 200

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

/**
 * Projects for the current organization.
 */
export const completeProductOnboardingPartialUpdateBodyNameMax = 200

export const completeProductOnboardingPartialUpdateBodyProductDescriptionMax = 1000

export const completeProductOnboardingPartialUpdateBodyAppUrlsItemMax = 200

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

/**
 * Projects for the current organization.
 */
export const deleteSecretTokenBackupPartialUpdateBodyNameMax = 200

export const deleteSecretTokenBackupPartialUpdateBodyProductDescriptionMax = 1000

export const deleteSecretTokenBackupPartialUpdateBodyAppUrlsItemMax = 200

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

/**
 * Projects for the current organization.
 */
export const generateConversationsPublicTokenCreateBodyNameMax = 200

export const generateConversationsPublicTokenCreateBodyProductDescriptionMax = 1000

export const generateConversationsPublicTokenCreateBodyAppUrlsItemMax = 200

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

/**
 * Projects for the current organization.
 */
export const resetTokenPartialUpdateBodyNameMax = 200

export const resetTokenPartialUpdateBodyProductDescriptionMax = 1000

export const resetTokenPartialUpdateBodyAppUrlsItemMax = 200

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

/**
 * Projects for the current organization.
 */
export const rotateSecretTokenPartialUpdateBodyNameMax = 200

export const rotateSecretTokenPartialUpdateBodyProductDescriptionMax = 1000

export const rotateSecretTokenPartialUpdateBodyAppUrlsItemMax = 200

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
 * Create a new password for the sharing configuration.
 */
export const InsightsSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const InsightsSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const projectSecretApiKeysCreateBodyLabelMax = 40

export const ProjectSecretApiKeysCreateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysCreateBodyLabelMax),
    scopes: zod.array(zod.string()),
})

export const projectSecretApiKeysUpdateBodyLabelMax = 40

export const ProjectSecretApiKeysUpdateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysUpdateBodyLabelMax),
    scopes: zod.array(zod.string()),
})

export const projectSecretApiKeysPartialUpdateBodyLabelMax = 40

export const ProjectSecretApiKeysPartialUpdateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysPartialUpdateBodyLabelMax).optional(),
    scopes: zod.array(zod.string()).optional(),
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

/**
 * Bulk update tags on multiple objects.

Accepts:
- {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}

Actions:
- "add": Add tags to existing tags on each object
- "remove": Remove specific tags from each object
- "set": Replace all tags on each object with the provided list
 */
export const propertyDefinitionsBulkUpdateTagsCreateBodyIdsMax = 500

export const PropertyDefinitionsBulkUpdateTagsCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.number())
        .max(propertyDefinitionsBulkUpdateTagsCreateBodyIdsMax)
        .describe('List of object IDs to update tags on.'),
    action: zod
        .enum(['add', 'remove', 'set'])
        .describe('* `add` - add\n* `remove` - remove\n* `set` - set')
        .describe(
            "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n* `add` - add\n* `remove` - remove\n* `set` - set"
        ),
    tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
})

/**
 * Create a new password for the sharing configuration.
 */
export const SessionRecordingsSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const SessionRecordingsSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const subscriptionsCreateBodyIntervalMin = -2147483648
export const subscriptionsCreateBodyIntervalMax = 2147483647

export const subscriptionsCreateBodyBysetposMin = -2147483648
export const subscriptionsCreateBodyBysetposMax = 2147483647

export const subscriptionsCreateBodyCountMin = -2147483648
export const subscriptionsCreateBodyCountMax = 2147483647

export const subscriptionsCreateBodyTitleMax = 100

export const subscriptionsCreateBodySummaryPromptGuideMax = 500

export const SubscriptionsCreateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod
            .number()
            .nullish()
            .describe('Dashboard ID to subscribe to (mutually exclusive with insight on create).'),
        insight: zod
            .number()
            .nullish()
            .describe('Insight ID to subscribe to (mutually exclusive with dashboard on create).'),
        dashboard_export_insights: zod
            .array(zod.number())
            .optional()
            .describe(
                'List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 6.'
            ),
        target_type: zod
            .enum(['email', 'slack', 'webhook'])
            .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook')
            .describe(
                'Delivery channel: email, slack, or webhook.\n\n* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'
            ),
        target_value: zod
            .string()
            .describe(
                'Recipient(s): comma-separated email addresses for email, Slack channel name/ID for slack, or full URL for webhook.'
            ),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly')
            .describe(
                'How often to deliver: daily, weekly, monthly, or yearly.\n\n* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'
            ),
        interval: zod
            .number()
            .min(subscriptionsCreateBodyIntervalMin)
            .max(subscriptionsCreateBodyIntervalMax)
            .optional()
            .describe('Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). Default 1.'),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish()
            .describe(
                'Days of week for weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.'
            ),
        bysetpos: zod
            .number()
            .min(subscriptionsCreateBodyBysetposMin)
            .max(subscriptionsCreateBodyBysetposMax)
            .nullish()
            .describe('Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last).'),
        count: zod
            .number()
            .min(subscriptionsCreateBodyCountMin)
            .max(subscriptionsCreateBodyCountMax)
            .nullish()
            .describe('Total number of deliveries before the subscription stops. Null for unlimited.'),
        start_date: zod.iso.datetime({}).describe('When to start delivering (ISO 8601 datetime).'),
        until_date: zod.iso
            .datetime({})
            .nullish()
            .describe('When to stop delivering (ISO 8601 datetime). Null for indefinite.'),
        deleted: zod.boolean().optional().describe('Set to true to soft-delete. Subscriptions cannot be hard-deleted.'),
        title: zod
            .string()
            .max(subscriptionsCreateBodyTitleMax)
            .nullish()
            .describe('Human-readable name for this subscription.'),
        integration_id: zod
            .number()
            .nullish()
            .describe('ID of a connected Slack integration. Required when target_type is slack.'),
        invite_message: zod
            .string()
            .nullish()
            .describe('Optional message included in the invitation email when adding new recipients.'),
        summary_enabled: zod.boolean().optional(),
        summary_prompt_guide: zod.string().max(subscriptionsCreateBodySummaryPromptGuideMax).optional(),
    })
    .describe('Standard Subscription serializer.')

export const subscriptionsUpdateBodyIntervalMin = -2147483648
export const subscriptionsUpdateBodyIntervalMax = 2147483647

export const subscriptionsUpdateBodyBysetposMin = -2147483648
export const subscriptionsUpdateBodyBysetposMax = 2147483647

export const subscriptionsUpdateBodyCountMin = -2147483648
export const subscriptionsUpdateBodyCountMax = 2147483647

export const subscriptionsUpdateBodyTitleMax = 100

export const subscriptionsUpdateBodySummaryPromptGuideMax = 500

export const SubscriptionsUpdateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod
            .number()
            .nullish()
            .describe('Dashboard ID to subscribe to (mutually exclusive with insight on create).'),
        insight: zod
            .number()
            .nullish()
            .describe('Insight ID to subscribe to (mutually exclusive with dashboard on create).'),
        dashboard_export_insights: zod
            .array(zod.number())
            .optional()
            .describe(
                'List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 6.'
            ),
        target_type: zod
            .enum(['email', 'slack', 'webhook'])
            .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook')
            .describe(
                'Delivery channel: email, slack, or webhook.\n\n* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'
            ),
        target_value: zod
            .string()
            .describe(
                'Recipient(s): comma-separated email addresses for email, Slack channel name/ID for slack, or full URL for webhook.'
            ),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly')
            .describe(
                'How often to deliver: daily, weekly, monthly, or yearly.\n\n* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'
            ),
        interval: zod
            .number()
            .min(subscriptionsUpdateBodyIntervalMin)
            .max(subscriptionsUpdateBodyIntervalMax)
            .optional()
            .describe('Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). Default 1.'),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish()
            .describe(
                'Days of week for weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.'
            ),
        bysetpos: zod
            .number()
            .min(subscriptionsUpdateBodyBysetposMin)
            .max(subscriptionsUpdateBodyBysetposMax)
            .nullish()
            .describe('Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last).'),
        count: zod
            .number()
            .min(subscriptionsUpdateBodyCountMin)
            .max(subscriptionsUpdateBodyCountMax)
            .nullish()
            .describe('Total number of deliveries before the subscription stops. Null for unlimited.'),
        start_date: zod.iso.datetime({}).describe('When to start delivering (ISO 8601 datetime).'),
        until_date: zod.iso
            .datetime({})
            .nullish()
            .describe('When to stop delivering (ISO 8601 datetime). Null for indefinite.'),
        deleted: zod.boolean().optional().describe('Set to true to soft-delete. Subscriptions cannot be hard-deleted.'),
        title: zod
            .string()
            .max(subscriptionsUpdateBodyTitleMax)
            .nullish()
            .describe('Human-readable name for this subscription.'),
        integration_id: zod
            .number()
            .nullish()
            .describe('ID of a connected Slack integration. Required when target_type is slack.'),
        invite_message: zod
            .string()
            .nullish()
            .describe('Optional message included in the invitation email when adding new recipients.'),
        summary_enabled: zod.boolean().optional(),
        summary_prompt_guide: zod.string().max(subscriptionsUpdateBodySummaryPromptGuideMax).optional(),
    })
    .describe('Standard Subscription serializer.')

export const subscriptionsPartialUpdateBodyIntervalMin = -2147483648
export const subscriptionsPartialUpdateBodyIntervalMax = 2147483647

export const subscriptionsPartialUpdateBodyBysetposMin = -2147483648
export const subscriptionsPartialUpdateBodyBysetposMax = 2147483647

export const subscriptionsPartialUpdateBodyCountMin = -2147483648
export const subscriptionsPartialUpdateBodyCountMax = 2147483647

export const subscriptionsPartialUpdateBodyTitleMax = 100

export const subscriptionsPartialUpdateBodySummaryPromptGuideMax = 500

export const SubscriptionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod
            .number()
            .nullish()
            .describe('Dashboard ID to subscribe to (mutually exclusive with insight on create).'),
        insight: zod
            .number()
            .nullish()
            .describe('Insight ID to subscribe to (mutually exclusive with dashboard on create).'),
        dashboard_export_insights: zod
            .array(zod.number())
            .optional()
            .describe(
                'List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 6.'
            ),
        target_type: zod
            .enum(['email', 'slack', 'webhook'])
            .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook')
            .optional()
            .describe(
                'Delivery channel: email, slack, or webhook.\n\n* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'
            ),
        target_value: zod
            .string()
            .optional()
            .describe(
                'Recipient(s): comma-separated email addresses for email, Slack channel name/ID for slack, or full URL for webhook.'
            ),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly')
            .optional()
            .describe(
                'How often to deliver: daily, weekly, monthly, or yearly.\n\n* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'
            ),
        interval: zod
            .number()
            .min(subscriptionsPartialUpdateBodyIntervalMin)
            .max(subscriptionsPartialUpdateBodyIntervalMax)
            .optional()
            .describe('Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). Default 1.'),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish()
            .describe(
                'Days of week for weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.'
            ),
        bysetpos: zod
            .number()
            .min(subscriptionsPartialUpdateBodyBysetposMin)
            .max(subscriptionsPartialUpdateBodyBysetposMax)
            .nullish()
            .describe('Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last).'),
        count: zod
            .number()
            .min(subscriptionsPartialUpdateBodyCountMin)
            .max(subscriptionsPartialUpdateBodyCountMax)
            .nullish()
            .describe('Total number of deliveries before the subscription stops. Null for unlimited.'),
        start_date: zod.iso.datetime({}).optional().describe('When to start delivering (ISO 8601 datetime).'),
        until_date: zod.iso
            .datetime({})
            .nullish()
            .describe('When to stop delivering (ISO 8601 datetime). Null for indefinite.'),
        deleted: zod.boolean().optional().describe('Set to true to soft-delete. Subscriptions cannot be hard-deleted.'),
        title: zod
            .string()
            .max(subscriptionsPartialUpdateBodyTitleMax)
            .nullish()
            .describe('Human-readable name for this subscription.'),
        integration_id: zod
            .number()
            .nullish()
            .describe('ID of a connected Slack integration. Required when target_type is slack.'),
        invite_message: zod
            .string()
            .nullish()
            .describe('Optional message included in the invitation email when adding new recipients.'),
        summary_enabled: zod.boolean().optional(),
        summary_prompt_guide: zod.string().max(subscriptionsPartialUpdateBodySummaryPromptGuideMax).optional(),
    })
    .describe('Standard Subscription serializer.')

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
