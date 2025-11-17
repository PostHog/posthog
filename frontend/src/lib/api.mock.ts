import apiReal from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { CurrencyCode } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    ActivationTaskStatus,
    CohortType,
    DataColorThemeModel,
    ExperimentStatsMethod,
    FilterLogicalOperator,
    GroupType,
    OrganizationInviteType,
    OrganizationMemberType,
    OrganizationType,
    PersonProperty,
    PluginConfigWithPluginInfo,
    PluginInstallationType,
    PluginType,
    ProjectType,
    PropertyFilterType,
    PropertyOperator,
    TeamType,
    UserBasicType,
    UserType,
} from '~/types'

import { OrganizationMembershipLevel, PluginsAccessLevel } from './constants'

export const MOCK_USER_UUID: UserType['uuid'] = 'USER_UUID'
export const MOCK_TEAM_ID: TeamType['id'] = 997
export const MOCK_TEAM_UUID: TeamType['uuid'] = 'TEAM_UUID'
export const MOCK_ORGANIZATION_ID: OrganizationType['id'] = 'ABCD'

type APIMockReturnType = {
    [K in keyof Pick<
        typeof apiReal,
        'create' | 'createResponse' | 'get' | 'getResponse' | 'update' | 'delete'
    >]: jest.Mock<ReturnType<(typeof apiReal)[K]>, Parameters<(typeof apiReal)[K]>>
} & {
    cohorts: typeof apiReal.cohorts
}

export const api = apiReal as any as APIMockReturnType

export const MOCK_DEFAULT_TEAM: TeamType = {
    id: MOCK_TEAM_ID,
    project_id: MOCK_TEAM_ID,
    uuid: MOCK_TEAM_UUID,
    organization: MOCK_ORGANIZATION_ID,
    api_token: 'default-team-api-token',
    secret_api_token: 'phs_default-team-secret-api-token',
    secret_api_token_backup: 'phs_default-team-secret-api-token-backup',
    app_urls: ['https://posthog.com/', 'https://app.posthog.com', 'https://example.com'],
    recording_domains: ['https://recordings.posthog.com/'],
    name: 'MockHog App + Marketing',
    slack_incoming_webhook: '',
    created_at: '2020-06-30T09:53:35.932534Z',
    updated_at: '2022-03-17T16:09:21.566253Z',
    anonymize_ips: false,
    completed_snippet_onboarding: true,
    ingested_event: true,
    test_account_filters: [
        {
            key: 'email',
            type: PropertyFilterType.Person,
            value: 'posthog.com',
            operator: PropertyOperator.NotIContains,
        },
    ],
    test_account_filters_default_checked: false,
    path_cleaning_filters: [],
    is_demo: false,
    timezone: 'UTC',
    data_attributes: ['data-attr'],
    person_display_name_properties: ['email', 'name', 'username'],
    correlation_config: {
        excluded_event_names: ['$autocapture', '$capture_metrics', '$feature_flag_called', '$groupidentify'],
        excluded_event_property_names: ['$plugins_deferred', '$geoip_time_zone'],
        excluded_person_property_names: ['$browser_version'],
    },
    autocapture_opt_out: true,
    session_recording_opt_in: true,
    session_recording_sample_rate: '1.0',
    session_recording_minimum_duration_milliseconds: null,
    session_recording_linked_flag: null,
    session_recording_network_payload_capture_config: { recordHeaders: true, recordBody: true },
    session_recording_masking_config: {
        maskAllInputs: true,
    },
    session_recording_retention_period: '30d',
    session_replay_config: null,
    capture_console_log_opt_in: true,
    capture_performance_opt_in: true,
    heatmaps_opt_in: true,
    autocapture_exceptions_opt_in: false,
    autocapture_web_vitals_opt_in: false,
    autocapture_exceptions_errors_to_ignore: [],
    effective_membership_level: OrganizationMembershipLevel.Admin,
    user_access_level: AccessControlLevel.Admin,
    group_types: [
        {
            group_type: 'organization',
            group_type_index: 0,
            name_singular: null,
            name_plural: 'organizations',
            default_columns: undefined,
            detail_dashboard: undefined,
        },
        {
            group_type: 'instance',
            group_type_index: 1,
            name_singular: null,
            name_plural: 'instances',
            default_columns: undefined,
            detail_dashboard: undefined,
        },
        {
            group_type: 'project',
            group_type_index: 2,
            name_singular: null,
            name_plural: 'projects',
            default_columns: undefined,
            detail_dashboard: undefined,
        },
    ],
    has_group_types: true,
    primary_dashboard: 1,
    live_events_columns: null,
    person_on_events_querying_enabled: true,
    live_events_token: '123',
    capture_dead_clicks: false,
    human_friendly_comparison_periods: false,
    revenue_analytics_config: {
        events: [
            {
                eventName: 'purchase',
                revenueProperty: 'value',
                revenueCurrencyProperty: { static: CurrencyCode.ZAR },
                subscriptionDropoffDays: 45,
                subscriptionDropoffMode: 'last_event',
                currencyAwareDecimal: false,
            },
            {
                eventName: 'subscription_created',
                revenueProperty: 'subscription_value',
                revenueCurrencyProperty: { property: 'currency' },
                subscriptionDropoffDays: 45,
                subscriptionDropoffMode: 'after_dropoff_period',
                currencyAwareDecimal: true,
            },
        ],
        filter_test_accounts: false,
        goals: [
            // Past goal
            {
                due_date: '2020-12-31',
                name: '2020 Q4',
                goal: 1_000_000,
                mrr_or_gross: 'gross',
            },
            // Very in the future to avoid flappy snapshots until 2035, assuming I'll be a multimillionaire by then and wont have to handle this
            // These are both "Current" goals since they're for the same day
            {
                due_date: '2035-12-31',
                name: '2035 Q4',
                goal: 1_500_000,
                mrr_or_gross: 'gross',
            },
            {
                due_date: '2035-12-31',
                name: '2035 Q4 MRR',
                goal: 1_200_000,
                mrr_or_gross: 'mrr',
            },
            // Future goal
            {
                due_date: '2040-12-31',
                name: '2040 Q4',
                goal: 1_800_000,
                mrr_or_gross: 'gross',
            },
        ],
    },
    flags_persistence_default: false,
    feature_flag_confirmation_enabled: false,
    feature_flag_confirmation_message: '',
    has_completed_onboarding_for: {
        product_analytics: true,
    },
    onboarding_tasks: {
        ingest_first_event: ActivationTaskStatus.COMPLETED,
        setup_session_recordings: ActivationTaskStatus.COMPLETED,
    },
    marketing_analytics_config: {
        sources_map: {},
    },
    base_currency: CurrencyCode.USD,
    default_evaluation_environments_enabled: false,
    managed_viewsets: { revenue_analytics: true },
    receive_org_level_activity_logs: false,
}

export const MOCK_DEFAULT_PROJECT: ProjectType = {
    id: MOCK_TEAM_ID,
    name: 'MockHog App + Marketing',
    organization_id: MOCK_ORGANIZATION_ID,
    created_at: '2020-06-30T09:53:35.932534Z',
}

export const MOCK_DEFAULT_ORGANIZATION: OrganizationType = {
    customer_id: null,
    id: MOCK_ORGANIZATION_ID,
    name: 'MockHog',
    slug: 'mockhog-fstn',
    created_at: '2020-09-24T15:05:01.254111Z',
    updated_at: '2022-01-03T13:50:55.369557Z',
    membership_level: OrganizationMembershipLevel.Admin,
    plugins_access_level: PluginsAccessLevel.Root,
    enforce_2fa: false,
    teams: [MOCK_DEFAULT_TEAM],
    projects: [MOCK_DEFAULT_PROJECT],
    is_member_join_email_enabled: true,
    members_can_use_personal_api_keys: true,
    allow_publicly_shared_resources: true,
    metadata: {},
    available_product_features: [],
    member_count: 2,
    logo_media_id: null,
    default_experiment_stats_method: ExperimentStatsMethod.Bayesian,
}

export const MOCK_DEFAULT_BASIC_USER: UserBasicType = {
    id: 178,
    uuid: MOCK_USER_UUID,
    distinct_id: 'mock-user-178-distinct-id',
    first_name: 'John',
    email: 'john.doe@posthog.com',
}

export const MOCK_DEFAULT_USER: UserType = {
    date_joined: '2023-02-28T13:03:32.333971Z',
    uuid: MOCK_USER_UUID,
    distinct_id: MOCK_DEFAULT_BASIC_USER.uuid,
    first_name: MOCK_DEFAULT_BASIC_USER.first_name,
    email: MOCK_DEFAULT_BASIC_USER.email,
    notification_settings: {
        plugin_disabled: false,
        project_weekly_digest_disabled: {},
        all_weekly_digest_disabled: false,
        error_tracking_issue_assigned: false,
        discussions_mentioned: false,
    },
    anonymize_data: false,
    toolbar_mode: 'toolbar',
    has_password: true,
    id: 179,
    is_staff: true,
    is_impersonated: false,
    is_email_verified: true,
    is_2fa_enabled: false,
    has_social_auth: false,
    has_sso_enforcement: false,
    sensitive_session_expires_at: dayjs().add(1, 'hour').toISOString(),
    theme_mode: null,
    team: MOCK_DEFAULT_TEAM,
    organization: MOCK_DEFAULT_ORGANIZATION,
    organizations: [MOCK_DEFAULT_ORGANIZATION].map(
        ({ id, name, slug, membership_level, members_can_use_personal_api_keys, allow_publicly_shared_resources }) => ({
            id,
            name,
            slug,
            membership_level,
            members_can_use_personal_api_keys,
            allow_publicly_shared_resources,
            logo_media_id: null,
        })
    ),
    events_column_config: {
        active: 'DEFAULT',
    },
}

export const MOCK_DEFAULT_ORGANIZATION_MEMBER: OrganizationMemberType = {
    id: '71fc7b7a-6267-47ae-ab62-f7f62aaed5da',
    user: MOCK_DEFAULT_BASIC_USER,
    level: OrganizationMembershipLevel.Owner,
    joined_at: '2020-09-24T15:05:26.758796Z',
    updated_at: '2020-09-24T15:05:26.758837Z',
    is_2fa_enabled: false,
    has_social_auth: false,
    last_login: '2020-09-24T15:05:26.758796Z',
}

export const MOCK_SECOND_BASIC_USER: UserBasicType = {
    id: 202,
    uuid: 'bf313676-e728-4221-a975-d8e90b9d168c',
    distinct_id: 'mock-user-202-distinct-id',
    first_name: 'Rose',
    email: 'rose.dawson@posthog.com',
}

export const MOCK_SECOND_ORGANIZATION_MEMBER: OrganizationMemberType = {
    id: '4622ae44-7818-4f4f-8dab-64894131d9e3',
    user: MOCK_SECOND_BASIC_USER,
    level: OrganizationMembershipLevel.Member,
    joined_at: '2021-03-11T19:11:11Z',
    updated_at: '2021-03-11T19:11:11Z',
    is_2fa_enabled: false,
    has_social_auth: false,
    last_login: '2020-09-24T15:05:26.758796Z',
}

export const MOCK_DEFAULT_ORGANIZATION_INVITE: OrganizationInviteType = {
    id: '83666ba4-4740-4ca3-94d9-d2b6b9b8afa6',
    target_email: 'test@posthog.com',
    first_name: '',
    emailing_attempt_made: true,
    is_expired: true,
    created_by: MOCK_DEFAULT_BASIC_USER,
    created_at: '2022-03-11T16:44:01.264613Z',
    updated_at: '2022-03-11T16:44:01.318717Z',
    level: OrganizationMembershipLevel.Member,
}

export const MOCK_PERSON_PROPERTIES: PersonProperty[] = [
    { id: 1, name: 'location', count: 1 },
    { id: 2, name: 'role', count: 2 },
    { id: 3, name: 'height', count: 3 },
    { id: 4, name: '$browser', count: 4 },
]

export const MOCK_DEFAULT_COHORT: CohortType = {
    id: 1,
    name: 'Paying Users',
    groups: [],
    filters: {
        properties: {
            id: '2',
            type: FilterLogicalOperator.Or,
            values: [],
        },
    },
}

export const MOCK_GROUP_TYPES: GroupType[] = [
    {
        group_type: 'organization',
        group_type_index: 0,
        name_singular: null,
        name_plural: 'organizations',
    },
    {
        group_type: 'instance',
        group_type_index: 1,
        name_singular: null,
        name_plural: 'instances',
    },
    {
        group_type: 'project',
        group_type_index: 2,
        name_singular: null,
        name_plural: 'projects',
    },
]

export const MOCK_DEFAULT_PLUGIN: PluginType = {
    id: 1,
    plugin_type: PluginInstallationType.Custom,
    name: 'Bazooka',
    description: 'Blow your data up',
    config_schema: [],
    tag: 'b65bbbbe126883babffc6fb06f448bfc65b5be7a',
    latest_tag: 'b65bbbbe126883babffc6fb06f448bfc65b5be7a',
    is_global: false,
    organization_id: MOCK_DEFAULT_ORGANIZATION.id,
    organization_name: MOCK_DEFAULT_ORGANIZATION.name,
    capabilities: {
        jobs: [],
        methods: ['processEvent'],
        scheduled_tasks: ['runEveryHour'],
    },
    metrics: {},
    public_jobs: {},
    // urls are hard-coded in frontend/src/scenes/pipeline/utils.tsx so it must be one of those URLs for tests to work
    url: 'https://github.com/PostHog/downsampling-plugin',
}

export const MOCK_DEFAULT_PLUGIN_CONFIG: PluginConfigWithPluginInfo = {
    id: 1,
    plugin: MOCK_DEFAULT_PLUGIN.id,
    enabled: true,
    order: 1,
    config: {},
    team_id: MOCK_TEAM_ID,
    delivery_rate_24h: 0.999,
    created_at: '2020-12-01T14:00:00.000Z',
    plugin_info: MOCK_DEFAULT_PLUGIN,
}

export const MOCK_DATA_COLOR_THEMES: DataColorThemeModel[] = [
    {
        id: 1,
        name: 'Default Theme',
        colors: [
            '#1d4aff',
            '#621da6',
            '#42827e',
            '#ce0e74',
            '#f14f58',
            '#7c440e',
            '#529a0a',
            '#0476fb',
            '#fe729e',
            '#35416b',
            '#41cbc4',
            '#b64b02',
            '#e4a604',
            '#a56eff',
            '#30d5c8',
        ],
        is_global: true,
    },
    {
        id: 2,
        name: 'Custom Theme',
        colors: ['#00ffff', '#ff00ff', '#ffff00'],
        is_global: false,
    },
]
