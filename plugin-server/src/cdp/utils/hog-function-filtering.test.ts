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
                  "distinct_id": "user_123",
                  "elements_chain": "",
                  "elements_chain_elements": [],
                  "elements_chain_href": "",
                  "elements_chain_ids": [],
                  "elements_chain_texts": [],
                  "event": "test_event",
                  "group_0": {
                    "index": 0,
                    "key": "org_123",
                    "properties": {
                      "name": "Acme Corp",
                    },
                  },
                  "group_1": {
                    "index": 1,
                    "key": "proj_456",
                    "properties": {
                      "name": "Project X",
                    },
                  },
                  "group_2": {
                    "index": 2,
                    "key": null,
                    "properties": {},
                  },
                  "group_3": {
                    "index": 3,
                    "key": null,
                    "properties": {},
                  },
                  "group_4": {
                    "index": 4,
                    "key": null,
                    "properties": {},
                  },
                  "organization": {
                    "index": 0,
                    "key": "org_123",
                    "properties": {
                      "name": "Acme Corp",
                    },
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
                  "project": {
                    "index": 1,
                    "key": "proj_456",
                    "properties": {
                      "name": "Project X",
                    },
                  },
                  "properties": {},
                  "timestamp": "2025-01-01T00:00:00.000Z",
                }
            `)
        })
    })
})
