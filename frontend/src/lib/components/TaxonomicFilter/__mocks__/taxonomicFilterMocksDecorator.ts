import { mswDecorator } from '~/mocks/browser'
import { mockActionDefinition } from '~/test/mocks'

export const taxonomicFilterMocksDecorator = mswDecorator({
    get: {
        '/api/projects/@current/actions': [mockActionDefinition],
        '/api/person/properties': [
            { id: 1, name: 'location', count: 1 },
            { id: 2, name: 'role', count: 2 },
            { id: 3, name: 'height', count: 3 },
            { id: 4, name: '$browser', count: 4 },
        ],
        '/api/projects/@current/property_definitions': [
            {
                id: 'a',
                name: 'signed up',
                description: 'signed up',
                volume_30_day: 10,
                query_usage_30_day: 5,
                count: 101,
            },
            {
                id: 'b',
                name: 'viewed insights',
                description: 'signed up',
                volume_30_day: 10,
                query_usage_30_day: 5,
                count: 1,
            },
            {
                id: 'c',
                name: 'logged out',
                description: 'signed up',
                volume_30_day: 10,
                query_usage_30_day: 5,
                count: 103,
            },
        ],
        '/api/projects/1/cohorts/': [
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
