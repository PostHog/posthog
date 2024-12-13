import { mswDecorator } from '~/mocks/browser'
import { mockActionDefinition } from '~/test/mocks'

export const taxonomicFilterMocksDecorator = mswDecorator({
    get: {
        '/api/projects/:team_id/actions': { results: [mockActionDefinition] },
        '/api/environments/:team_id/persons/properties': [
            { id: 1, name: 'location', count: 1 },
            { id: 2, name: 'role', count: 2 },
            { id: 3, name: 'height', count: 3 },
            { id: 4, name: '$browser', count: 4 },
        ],
        '/api/projects/:team_id/property_definitions': [
            {
                name: 'file_count',
                count: 205,
            },
            {
                name: 'industry',
                count: 205,
            },
            {
                name: 'name',
                count: 205,
            },
            {
                name: 'plan',
                count: 205,
            },
            {
                name: 'team_size',
                count: 205,
            },
            {
                name: 'used_mb',
                count: 205,
            },
        ],
        '/api/projects/:team_id/event_definitions': [
            {
                id: 'a',
                name: 'signed up',
                description: 'signed up',
                count: 101,
            },
            {
                id: 'b',
                name: 'viewed insights',
                description: 'signed up',
                count: 1,
                verified: true,
            },
            {
                id: 'c',
                name: 'logged out',
                description: 'signed up',
                count: 103,
            },
        ],
        '/api/projects/:team_id/cohorts/': [
            {
                id: 1,
                name: 'Properties Cohort',
                count: 1,
                groups: [{ id: 'a', name: 'Properties Group', count: 1, matchType: 'properties' }],
            },
            {
                id: 2,
                name: 'Entities Cohort',
                count: 1,
                groups: [{ id: 'b', name: 'Entities Group', count: 1, matchType: 'entities' }],
            },
        ],
    },
})
