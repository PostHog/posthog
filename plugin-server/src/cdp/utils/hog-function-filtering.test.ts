import { HogFunctionInvocationGlobals } from '../types'
import { convertToHogFunctionFilterGlobal } from './hog-function-filtering'

describe('hog-function-filtering', () => {
    describe('convertToHogFunctionFilterGlobal', () => {
        it('should correctly map groups to response including empty group indexes', () => {
            const globals: HogFunctionInvocationGlobals = {
                project: {
                    id: 1,
                    name: 'Test Project',
                    url: 'http://example.com',
                },
                event: {
                    uuid: 'event_uuid',
                    event: 'test_event',
                    distinct_id: 'user_123',
                    properties: {},
                    elements_chain: '',
                    timestamp: '2025-01-01T00:00:00.000Z',
                    url: 'http://example.com/event',
                },
                person: {
                    id: 'person_123',
                    properties: {},
                    name: 'Test User',
                    url: 'http://example.com/person',
                },
                groups: {
                    organization: {
                        id: 'org_123',
                        type: 'organization',
                        index: 0,
                        properties: { name: 'Acme Corp' },
                        url: 'http://example.com/org',
                    },
                    project: {
                        id: 'proj_456',
                        type: 'project',
                        index: 1,
                        properties: { name: 'Project X' },
                        url: 'http://example.com/project',
                    },
                },
            }

            const response = convertToHogFunctionFilterGlobal(globals)

            expect(response).toMatchInlineSnapshot(`
                {
                  "$group_0": "org_123",
                  "$group_1": "proj_456",
                  "$group_2": null,
                  "$group_3": null,
                  "$group_4": null,
                  "distinct_id": "user_123",
                  "elements_chain": "",
                  "elements_chain_elements": [],
                  "elements_chain_href": "",
                  "elements_chain_ids": [],
                  "elements_chain_texts": [],
                  "event": "test_event",
                  "group_0": {
                    "properties": {
                      "name": "Acme Corp",
                    },
                  },
                  "group_1": {
                    "properties": {
                      "name": "Project X",
                    },
                  },
                  "group_2": {
                    "properties": {},
                  },
                  "group_3": {
                    "properties": {},
                  },
                  "group_4": {
                    "properties": {},
                  },
                  "pdi": {
                    "distinct_id": "user_123",
                    "person": {
                      "id": "person_123",
                      "properties": {},
                    },
                    "person_id": "person_123",
                  },
                  "person": {
                    "id": "person_123",
                    "properties": {},
                  },
                  "properties": {},
                  "timestamp": "2025-01-01T00:00:00.000Z",
                }
            `)
        })
    })
})
