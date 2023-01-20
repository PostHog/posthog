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

const API_NOOP = { count: 0, results: [] as any[], next: null, previous: null }
const apiResults = (results: any[]): typeof API_NOOP => ({ count: results.length, results, next: null, previous: null })

export const defaultMocks: Mocks = {
    get: {
        '/api/projects/:team_id/actions/': API_NOOP,
        '/api/projects/:team_id/annotations/': API_NOOP,
        '/api/projects/:team_id/event_definitions/': API_NOOP,
        '/api/projects/:team_id/cohorts/': apiResults([MOCK_DEFAULT_COHORT]),
        '/api/projects/:team_id/dashboards/': API_NOOP,
        '/api/projects/:team_id/groups/': API_NOOP,
        '/api/projects/:team_id/insights/': API_NOOP,
        '/api/projects/:team_id/property_definitions/': API_NOOP,
        '/api/projects/:team_id/feature_flags/': API_NOOP,
        '/api/projects/:team_id/explicit_members/': [],
        '/api/organizations/@current/': (): MockSignature => [
            200,
            { ...MOCK_DEFAULT_ORGANIZATION, available_features: getAvailableFeatures() },
        ],
        '/api/organizations/@current/members/': apiResults([MOCK_DEFAULT_ORGANIZATION_MEMBER]),
        '/api/organizations/@current/invites/': apiResults([MOCK_DEFAULT_ORGANIZATION_INVITE]),
        '/api/organizations/@current/plugins/': apiResults([]),
        '/api/projects/@current/persons/properties/': apiResults(MOCK_PERSON_PROPERTIES),
        '/api/projects/:team_id/persons': apiResults([]),
        '/api/projects/:team_id/persons/properties/': apiResults(MOCK_PERSON_PROPERTIES),
        '/api/personal_api_keys/': [],
        '/api/license/': apiResults([MOCK_DEFAULT_LICENSE]),
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
        '/api/plugin_config/': apiResults([]),
        'https://update.posthog.com/': [{ version: '1.42.0', release_date: '2022-11-30' }],
    },
    post: {
        '/e/': (): MockSignature => [200, 'ok'],
        'https://app.posthog.com/decide/': (): MockSignature => [200, 'ok'],
        '/decide/': (): MockSignature => [200, 'ok'],
        'https://app.posthog.com/engage/': (): MockSignature => [200, 'ok'],
        'https://app.posthog.com/e/': (): MockSignature => [200, 'ok'],
    },
    patch: {
        '/api/prompts/my_prompts': (): MockSignature => [200, {}],
    },
}
export const handlers = mocksToHandlers(defaultMocks)
