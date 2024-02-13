import {
    MOCK_DEFAULT_COHORT,
    MOCK_DEFAULT_ORGANIZATION,
    MOCK_DEFAULT_ORGANIZATION_INVITE,
    MOCK_DEFAULT_ORGANIZATION_MEMBER,
    MOCK_DEFAULT_PLUGIN,
    MOCK_DEFAULT_PLUGIN_CONFIG,
    MOCK_DEFAULT_TEAM,
    MOCK_DEFAULT_USER,
    MOCK_PERSON_PROPERTIES,
    MOCK_SECOND_ORGANIZATION_MEMBER,
} from 'lib/api.mock'

import { getAvailableFeatures } from '~/mocks/features'
import { SharingConfigurationType } from '~/types'

import { Mocks, MockSignature, mocksToHandlers } from './utils'

export const EMPTY_PAGINATED_RESPONSE = { count: 0, results: [] as any[], next: null, previous: null }
export const toPaginatedResponse = (results: any[]): typeof EMPTY_PAGINATED_RESPONSE => ({
    count: results.length,
    results,
    next: null,
    previous: null,
})

export const defaultMocks: Mocks = {
    get: {
        '/api/projects/:team_id/activity_log/important_changes/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/actions/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/annotations/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/event_definitions/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/cohorts/': toPaginatedResponse([MOCK_DEFAULT_COHORT]),
        '/api/projects/:team_id/dashboards/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/dashboard_templates': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/dashboard_templates/repository/': [],
        '/api/projects/:team_id/notebooks': () => {
            // this was matching on `?contains=query` but that made MSW unhappy and seems unnecessary
            return [
                200,
                {
                    count: 0,
                    results: [],
                },
            ]
        },
        '/api/projects/:team_id/groups/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/groups_types/': [],
        '/api/projects/:team_id/insights/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/insights/:insight_id/sharing/': {
            enabled: false,
            access_token: 'foo',
            created_at: '2020-11-11T00:00:00Z',
        } as SharingConfigurationType,
        '/api/projects/:team_id/property_definitions/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/feature_flags/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/feature_flags/:feature_flag_id/role_access': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/experiments/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/explicit_members/': [],
        '/api/projects/:team_id/warehouse_view_link/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/warehouse_saved_queries/': EMPTY_PAGINATED_RESPONSE,
        '/api/organizations/@current/': (): MockSignature => [
            200,
            { ...MOCK_DEFAULT_ORGANIZATION, available_features: getAvailableFeatures() },
        ],
        '/api/organizations/@current/roles/': EMPTY_PAGINATED_RESPONSE,
        '/api/organizations/@current/members/': toPaginatedResponse([
            MOCK_DEFAULT_ORGANIZATION_MEMBER,
            MOCK_SECOND_ORGANIZATION_MEMBER,
        ]),
        '/api/organizations/@current/invites/': toPaginatedResponse([MOCK_DEFAULT_ORGANIZATION_INVITE]),
        '/api/organizations/@current/plugins/': toPaginatedResponse([MOCK_DEFAULT_PLUGIN]),
        '/api/organizations/@current/plugins/repository/': [],
        '/api/organizations/@current/plugins/unused/': [],
        '/api/plugin_config/': toPaginatedResponse([MOCK_DEFAULT_PLUGIN_CONFIG]),
        [`/api/projects/:team_id/plugin_configs/${MOCK_DEFAULT_PLUGIN_CONFIG.id}/`]: MOCK_DEFAULT_PLUGIN_CONFIG,
        '/api/projects/:team_id/persons': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/persons/properties/': toPaginatedResponse(MOCK_PERSON_PROPERTIES),
        '/api/personal_api_keys/': [],
        '/api/users/@me/': (): MockSignature => [
            200,
            {
                ...MOCK_DEFAULT_USER,
                organization: { ...MOCK_DEFAULT_ORGANIZATION, available_features: getAvailableFeatures() },
            },
        ],
        '/api/projects/@current/': MOCK_DEFAULT_TEAM,
        '/api/billing-v2/': (): MockSignature => [200, {}],
        '/api/projects/:team_id/comments/count': { count: 0 },
        '/api/projects/:team_id/comments': { results: [] },
        '/_preflight': require('./fixtures/_preflight.json'),
        '/_system_status': require('./fixtures/_system_status.json'),
        '/api/instance_status': require('./fixtures/_instance_status.json'),
        // TODO: Add a real mock once we know why this endpoint returns an error inside a 200 response
        '/api/sentry_stats/': {
            error: 'Error fetching stats from sentry',
            exception: "[ErrorDetail(string='Sentry integration not configured', code='invalid')]",
        },
        // We don't want to show the "new version available" banner in tests
        'https://api.github.com/repos/posthog/posthog-js/tags': () => [200, []],
        'https://www.gravatar.com/avatar/:gravatar_id': () => [404, ''],
        'https://app.posthog.com/api/early_access_features': {
            earlyAccessFeatures: [],
        },
    },
    post: {
        'https://app.posthog.com/e/': (): MockSignature => [200, 'ok'],
        '/e/': (): MockSignature => [200, 'ok'],
        'https://app.posthog.com/decide/': (): MockSignature => [200, 'ok'],
        '/decide/': (): MockSignature => [200, 'ok'],
        'https://app.posthog.com/engage/': (): MockSignature => [200, 'ok'],
        '/api/projects/:team_id/insights/:insight_id/viewed/': (): MockSignature => [201, null],
    },
}
export const handlers = mocksToHandlers(defaultMocks)
