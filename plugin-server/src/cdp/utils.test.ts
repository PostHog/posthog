import { DateTime } from 'luxon'

import { insertHogFunction as _insertHogFunction } from './_tests/fixtures'
import { HogFunctionInvocationGlobals, HogFunctionInvocationLogEntry } from './types'
import { convertToHogFunctionFilterGlobal, fixLogDeduplication, gzipObject, unGzipObject } from './utils'

describe('Utils', () => {
    describe('gzip compressions', () => {
        it("should compress and decompress a string using gzip's sync functions", async () => {
            const input = { foo: 'bar', foo2: 'bar' }
            const compressed = await gzipObject(input)
            expect(compressed).toHaveLength(52)
            const decompressed = await unGzipObject(compressed)
            expect(decompressed).toEqual(input)
        })
    })

    describe('fixLogDeduplication', () => {
        const commonProps = {
            team_id: 1,
            log_source: 'hog_function',
            log_source_id: 'hog-1',
            instance_id: 'inv-1',
            level: 'info' as const,
        }
        const startTime = DateTime.fromMillis(1620000000000)
        const example: HogFunctionInvocationLogEntry[] = [
            {
                ...commonProps,
                timestamp: startTime.plus(2),
                message: 'Third log message',
            },
            {
                ...commonProps,
                timestamp: startTime,
                message: 'First log message',
            },
            {
                ...commonProps,
                timestamp: startTime.plus(1),
                message: 'Second log message',
            },
            {
                ...commonProps,
                timestamp: startTime.plus(2),
                message: 'Duplicate log message',
            },
        ]

        it('should add the relevant info to the logs', () => {
            const prepared = fixLogDeduplication(example)

            expect(prepared).toMatchInlineSnapshot(`
                [
                  {
                    "instance_id": "inv-1",
                    "level": "info",
                    "log_source": "hog_function",
                    "log_source_id": "hog-1",
                    "message": "First log message",
                    "team_id": 1,
                    "timestamp": "2021-05-03 00:00:00.000",
                  },
                  {
                    "instance_id": "inv-1",
                    "level": "info",
                    "log_source": "hog_function",
                    "log_source_id": "hog-1",
                    "message": "Second log message",
                    "team_id": 1,
                    "timestamp": "2021-05-03 00:00:00.001",
                  },
                  {
                    "instance_id": "inv-1",
                    "level": "info",
                    "log_source": "hog_function",
                    "log_source_id": "hog-1",
                    "message": "Third log message",
                    "team_id": 1,
                    "timestamp": "2021-05-03 00:00:00.002",
                  },
                  {
                    "instance_id": "inv-1",
                    "level": "info",
                    "log_source": "hog_function",
                    "log_source_id": "hog-1",
                    "message": "Duplicate log message",
                    "team_id": 1,
                    "timestamp": "2021-05-03 00:00:00.003",
                  },
                ]
            `)
        })
    })

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
