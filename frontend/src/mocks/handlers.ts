import { Mocks, MockSignature, mocksToHandlers } from './utils'
import {
    MOCK_DEFAULT_LICENSE,
    MOCK_DEFAULT_ORGANIZATION,
    MOCK_DEFAULT_ORGANIZATION_INVITE,
    MOCK_DEFAULT_ORGANIZATION_MEMBER,
    MOCK_DEFAULT_TEAM,
    MOCK_DEFAULT_USER,
    MOCK_DEFAULT_COHORT,
    MOCK_PERSON_PROPERTIES,
} from 'lib/api.mock'
import { getAvailableFeatures } from '~/mocks/features'
import { SharingConfigurationType } from '~/types'

export const EMPTY_PAGINATED_RESPONSE = { count: 0, results: [] as any[], next: null, previous: null }
export const toPaginatedResponse = (results: any[]): typeof EMPTY_PAGINATED_RESPONSE => ({
    count: results.length,
    results,
    next: null,
    previous: null,
})

export const defaultMocks: Mocks = {
    get: {
        '/api/projects/:team_id/actions/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/annotations/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/event_definitions/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/cohorts/': toPaginatedResponse([MOCK_DEFAULT_COHORT]),
        '/api/projects/:team_id/dashboards/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/groups/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/insights/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/insights/:insight_id/sharing/': {
            enabled: false,
            access_token: 'foo',
            created_at: '2020-11-11T00:00:00Z',
        } as SharingConfigurationType,
        '/api/projects/:team_id/property_definitions/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/feature_flags/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/explicit_members/': [],
        '/api/organizations/@current/': (): MockSignature => [
            200,
            { ...MOCK_DEFAULT_ORGANIZATION, available_features: getAvailableFeatures() },
        ],
        '/api/organizations/@current/members/': toPaginatedResponse([MOCK_DEFAULT_ORGANIZATION_MEMBER]),
        '/api/organizations/@current/invites/': toPaginatedResponse([MOCK_DEFAULT_ORGANIZATION_INVITE]),
        '/api/organizations/@current/plugins/': toPaginatedResponse([]),
        '/api/organizations/@current/plugins/repository/': [],
        '/api/projects/@current/dashboard_templates/repository/': [],
        '/api/projects/@current/persons/properties/': toPaginatedResponse(MOCK_PERSON_PROPERTIES),
        '/api/projects/:team_id/persons': toPaginatedResponse([]),
        '/api/projects/:team_id/persons/properties/': toPaginatedResponse(MOCK_PERSON_PROPERTIES),
        '/api/personal_api_keys/': [],
        '/api/license/': toPaginatedResponse([MOCK_DEFAULT_LICENSE]),
        '/api/users/@me/': (): MockSignature => [
            200,
            {
                ...MOCK_DEFAULT_USER,
                organization: { ...MOCK_DEFAULT_ORGANIZATION, available_features: getAvailableFeatures() },
            },
        ],
        '/api/projects/@current/': MOCK_DEFAULT_TEAM,
        '/api/billing-v2/': (): MockSignature => [200, {}],
        '/_preflight': require('./fixtures/_preflight.json'),
        '/_system_status': require('./fixtures/_system_status.json'),
        '/api/instance_status': require('./fixtures/_instance_status.json'),
        '/api/plugin_config/': toPaginatedResponse([]),
        'https://update.posthog.com/': [{ version: '1.42.0', release_date: '2022-11-30' }],
    },
    post: {
        'https://app.posthog.com/e/': (): MockSignature => [200, 'ok'],
        '/e/': (): MockSignature => [200, 'ok'],
        'https://app.posthog.com/decide/': (): MockSignature => [200, 'ok'],
        '/decide/': (): MockSignature => [200, 'ok'],
        'https://app.posthog.com/engage/': (): MockSignature => [200, 'ok'],
        '/api/projects/:team_id/insights/:insight_id/viewed/': (): MockSignature => [201, null],
    },
    patch: {
        '/api/prompts/my_prompts': (): MockSignature => [200, {}],
    },
}
export const handlers = mocksToHandlers(defaultMocks)
