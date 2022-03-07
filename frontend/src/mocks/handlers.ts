import { mocksToHandlers } from './utils'
import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

const API_NOOP = { results: [], next: null }

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

        '/api/organizations/@current/': MOCK_DEFAULT_ORGANIZATION,
        '/api/users/@me/': {
            organization: MOCK_DEFAULT_ORGANIZATION,
            team: MOCK_DEFAULT_TEAM,
        },
        '/api/projects/@current/': MOCK_DEFAULT_TEAM,
        '/_preflight': require('../../../cypress/fixtures/_preflight.json'),
        '/_system_status': require('../../../cypress/fixtures/_system_status.json'),
    },
    post: {
        '/e/': () => [200, 'ok'],
    },
})
