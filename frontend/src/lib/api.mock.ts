import {
    CohortType,
    FilterLogicalOperator,
    GroupType,
    LicensePlan,
    LicenseType,
    OrganizationInviteType,
    OrganizationMemberType,
    OrganizationType,
    PersonProperty,
    PropertyOperator,
    TeamType,
    UserBasicType,
    UserType,
} from '~/types'
import { OrganizationMembershipLevel, PluginsAccessLevel } from './constants'
import apiReal from 'lib/api'

export const MOCK_USER_UUID: UserType['uuid'] = 'USER_UUID'
export const MOCK_TEAM_ID: TeamType['id'] = 997
export const MOCK_TEAM_UUID: TeamType['uuid'] = 'TEAM_UUID'
export const MOCK_ORGANIZATION_ID: OrganizationType['id'] = 'ABCD'

type APIMockReturnType = {
    [K in keyof Pick<typeof apiReal, 'create' | 'get' | 'update' | 'delete'>]: jest.Mock<
        ReturnType<typeof apiReal[K]>,
        Parameters<typeof apiReal[K]>
    >
}

export const api = apiReal as any as APIMockReturnType

export const MOCK_DEFAULT_TEAM: TeamType = {
    id: MOCK_TEAM_ID,
    uuid: MOCK_TEAM_UUID,
    organization: MOCK_ORGANIZATION_ID,
    api_token: 'default-team-api-token',
    app_urls: ['https://posthog.com/', 'https://app.posthog.com'],
    name: 'MockHog App + Marketing',
    slack_incoming_webhook: '',
    created_at: '2020-06-30T09:53:35.932534Z',
    updated_at: '2022-03-17T16:09:21.566253Z',
    anonymize_ips: false,
    completed_snippet_onboarding: true,
    ingested_event: true,
    test_account_filters: [
        { key: 'email', type: 'person', value: 'posthog.com', operator: PropertyOperator.NotIContains },
    ],
    path_cleaning_filters: [],
    is_demo: false,
    timezone: 'Europe/Brussels',
    data_attributes: ['data-attr'],
    person_display_name_properties: ['email', 'name', 'username'],
    correlation_config: {
        excluded_event_names: ['$autocapture', '$capture_metrics', '$feature_flag_called', '$groupidentify'],
        excluded_event_property_names: ['$plugins_deferred', '$geoip_time_zone'],
        excluded_person_property_names: ['$browser_version'],
    },
    session_recording_opt_in: true,
    effective_membership_level: OrganizationMembershipLevel.Admin,
    access_control: true,
    has_group_types: true,
    primary_dashboard: 1,
    live_events_columns: ['event', 'person'],
}

export const MOCK_DEFAULT_ORGANIZATION: OrganizationType = {
    id: MOCK_ORGANIZATION_ID,
    name: 'MockHog',
    slug: 'mockhog-fstn',
    created_at: '2020-09-24T15:05:01.254111Z',
    updated_at: '2022-01-03T13:50:55.369557Z',
    membership_level: OrganizationMembershipLevel.Admin,
    plugins_access_level: PluginsAccessLevel.Root,
    teams: [MOCK_DEFAULT_TEAM],
    available_features: [],
    is_member_join_email_enabled: true,
    metadata: {
        taxonomy_set_events_count: 60,
        taxonomy_set_properties_count: 17,
    },
}

export const MOCK_DEFAULT_BASIC_USER: UserBasicType = {
    id: 178,
    uuid: MOCK_USER_UUID,
    distinct_id: 'mock-user-178-distinct-id',
    first_name: 'John',
    email: 'john.doe@posthog.com',
}

export const MOCK_DEFAULT_USER: UserType = {
    date_joined: '2022-03-11T13:03:32.333971Z',
    uuid: MOCK_USER_UUID,
    distinct_id: 'mock-user-178-distinct-id',
    first_name: 'John',
    email: 'john.doe@posthog.com',
    email_opt_in: true,
    anonymize_data: false,
    toolbar_mode: 'toolbar',
    has_password: true,
    is_staff: true,
    is_impersonated: false,
    team: MOCK_DEFAULT_TEAM,
    organization: MOCK_DEFAULT_ORGANIZATION,
    organizations: [MOCK_DEFAULT_ORGANIZATION].map(({ id, name, slug, membership_level }) => ({
        id,
        name,
        slug,
        membership_level,
    })),
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
}

export const MOCK_DEFAULT_LICENSE: LicenseType = {
    id: 1,
    key: 'license-key',
    plan: LicensePlan.Scale,
    valid_until: '2025-03-11T14:05:45.338000Z',
    max_users: 21312,
    created_at: '2022-03-11T14:05:36.107000Z',
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
