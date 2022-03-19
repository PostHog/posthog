import { mocksToHandlers } from './utils'
import {
    MOCK_DEFAULT_LICENSE,
    MOCK_DEFAULT_ORGANIZATION,
    MOCK_DEFAULT_ORGANIZATION_INVITE,
    MOCK_DEFAULT_ORGANIZATION_MEMBER,
    MOCK_DEFAULT_TEAM,
    MOCK_PERSON_PROPERTIES,
} from 'lib/api.mock'
import { getFeatures } from '~/mocks/features'

const API_NOOP = { count: 0, results: [] as any[], next: null, previous: null }
const apiResults = (results: any[]): typeof API_NOOP => ({ count: results.length, results, next: null, previous: null })

export const handlers = mocksToHandlers({
    get: {
        '/api/projects/:team_id/actions/': API_NOOP,
        '/api/projects/:team_id/annotations/': API_NOOP,
        '/api/projects/:team_id/event_definitions/': API_NOOP,
        '/api/projects/:team_id/cohorts/': API_NOOP,
        '/api/projects/:team_id/dashboards/': API_NOOP,
        '/api/projects/:team_id/groups/': API_NOOP,
        '/api/projects/:team_id/insights/': API_NOOP,
        '/api/projects/:team_id/property_definitions/': API_NOOP,
        '/api/projects/:team_id/feature_flags/': API_NOOP,
        '/api/projects/:team_id/explicit_members/': [],
        '/api/organizations/@current/': { ...MOCK_DEFAULT_ORGANIZATION, available_features: getFeatures() },
        '/api/organizations/@current/members/': apiResults([MOCK_DEFAULT_ORGANIZATION_MEMBER]),
        '/api/organizations/@current/invites/': apiResults([MOCK_DEFAULT_ORGANIZATION_INVITE]),
        '/api/person/properties/': apiResults(MOCK_PERSON_PROPERTIES),
        '/api/personal_api_keys/': [],
        '/api/license/': apiResults([MOCK_DEFAULT_LICENSE]),
        '/api/users/@me/': {
            organization: { ...MOCK_DEFAULT_ORGANIZATION, available_features: getFeatures() },
            team: MOCK_DEFAULT_TEAM,
        },
        '/api/projects/@current/': MOCK_DEFAULT_TEAM,
        '/_preflight': require('./fixtures/_preflight.json'),
        '/_system_status': require('./fixtures/_system_status.json'),
        '/api/instance_status': require('./fixtures/_instance_status.json'),
    },
    post: {
        '/e/': () => [200, 'ok'],
        '/decide/': () => [200, 'ok'],
        'https://app.posthog.com/decide/': () => [200, 'ok'],
    },
})
