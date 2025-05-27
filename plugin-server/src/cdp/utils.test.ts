import { DateTime } from 'luxon'

import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './_tests/examples'
import {
    createHogExecutionGlobals,
    createHogFunction,
    insertHogFunction as _insertHogFunction,
} from './_tests/fixtures'
import { HogFunctionInvocationGlobals, HogFunctionInvocationLogEntry } from './types'
import {
    cloneInvocation,
    convertToHogFunctionFilterGlobal,
    createInvocation,
    fixLogDeduplication,
    gzipObject,
    unGzipObject,
} from './utils'

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

    describe('cloneInvocation', () => {
        beforeEach(() => {
            const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
            jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        const invocation = createInvocation(
            {
                ...createHogExecutionGlobals(),
                inputs: { foo: 'bar' },
            },
            createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.elements_href_filter,
            })
        )

        invocation.queueSource = 'postgres'

        it('should clone an invocation', () => {
            const cloned = cloneInvocation(invocation, {
                queue: 'hog',
            })
            const { id, globals, hogFunction, ...rest } = cloned
            expect(id).toBe(invocation.id)
            expect(globals).toBe(invocation.globals)
            expect(hogFunction).toBe(invocation.hogFunction)

            expect(rest).toMatchInlineSnapshot(`
                {
                  "queue": "hog",
                  "queueMetadata": undefined,
                  "queueParameters": undefined,
                  "queuePriority": 0,
                  "queueScheduledAt": undefined,
                  "queueSource": "postgres",
                  "teamId": 1,
                  "timings": [],
                }
            `)
        })

        it('should allow overriding properties', () => {
            const cloned = cloneInvocation(invocation, {
                queue: 'hog',
                queuePriority: 1,
                queueMetadata: { foo: 'bar' },
                queueScheduledAt: DateTime.now(),
                queueParameters: {
                    response: {
                        headers: {},
                        status: 200,
                    },
                },
            })

            const { id, globals, hogFunction, ...rest } = cloned
            expect(id).toBe(invocation.id)
            expect(globals).toBe(invocation.globals)
            expect(hogFunction).toBe(invocation.hogFunction)

            expect(rest).toMatchInlineSnapshot(`
                {
                  "queue": "hog",
                  "queueMetadata": {
                    "foo": "bar",
                  },
                  "queueParameters": {
                    "response": {
                      "headers": {},
                      "status": 200,
                    },
                  },
                  "queuePriority": 1,
                  "queueScheduledAt": "2025-01-01T01:00:00.000+01:00",
                  "queueSource": "postgres",
                  "teamId": 1,
                  "timings": [],
                }
            `)
        })
    })
})
