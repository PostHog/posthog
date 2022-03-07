import { mocksToHandlers } from './utils'

const API_NOOP = { results: [], next: null }

export const handlers = mocksToHandlers({
    get: {
        '/api/projects/:team_id/actions/': () => [200, API_NOOP],
        '/api/projects/:team_id/annotations/': () => [200, API_NOOP],
        '/api/projects/:team_id/event_definitions/': () => [200, API_NOOP],
        '/api/projects/:team_id/cohorts/': () => [200, API_NOOP],
        '/api/projects/:team_id/dashboards/': () => [200, API_NOOP],
        '/api/projects/:team_id/groups/': () => [200, API_NOOP],
        '/api/projects/:team_id/insights/': () => [200, API_NOOP],
        '/api/projects/:team_id/property_definitions/': () => [200, API_NOOP],
        '/api/organizations/@current/': () => [
            200,
            require('../../../cypress/fixtures/api/organizations/@current.json'),
        ],
        '/api/users/@me/': () => [200, require('../../../cypress/fixtures/api/users/@me.json')],
        '/_preflight': () => [200, require('../../../cypress/fixtures/_preflight.json')],
        '/_system_status': () => [200, require('../../../cypress/fixtures/_system_status.json')],
    },
    post: {
        '/e/': () => [200, 'ok'],
    },
})
