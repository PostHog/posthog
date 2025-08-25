import { ClickHouseTimestamp, ProjectId, RawClickHouseEvent } from '../../types'
import { HogFunctionInvocationGlobals } from '../types'
import { convertClickhouseRawEventToFilterGlobals, convertToHogFunctionFilterGlobal } from './hog-function-filtering'

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

    describe('convertClickhouseRawEventToFilterGlobals', () => {
        it('should convert RawClickHouseEvent to HogFunctionFilterGlobals with basic event data', () => {
            const rawEvent: RawClickHouseEvent = {
                uuid: 'event_uuid',
                event: 'test_event',
                team_id: 1,
                distinct_id: 'user_123',
                project_id: 1 as ProjectId,
                timestamp: '2025-01-01T00:00:00.000Z' as ClickHouseTimestamp,
                created_at: '2025-01-01T00:00:00.000Z' as ClickHouseTimestamp,
                properties: JSON.stringify({ test_prop: 'test_value' }),
                elements_chain: 'a:href="https://example.com"',
                person_mode: 'full',
            }

            const result = convertClickhouseRawEventToFilterGlobals(rawEvent)

            expect(result.event).toBe('test_event')
            expect(result.distinct_id).toBe('user_123')
            expect(result.timestamp).toBe('2025-01-01T00:00:00.000Z')
            expect(result.properties).toEqual({ test_prop: 'test_value' })
            expect(result.elements_chain).toBe('a:href="https://example.com"')
            expect(result.elements_chain_href).toBe('https://example.com')
            expect(result.person).toBeNull()
            expect(result.pdi).toBeNull()
        })

        it('should handle person data when person_id is present', () => {
            const rawEvent: RawClickHouseEvent = {
                uuid: 'event_uuid',
                event: 'test_event',
                team_id: 1,
                distinct_id: 'user_123',
                project_id: 1 as ProjectId,
                timestamp: '2025-01-01T00:00:00.000Z' as ClickHouseTimestamp,
                created_at: '2025-01-01T00:00:00.000Z' as ClickHouseTimestamp,
                properties: JSON.stringify({}),
                elements_chain: '',
                person_id: 'person_123',
                person_properties: JSON.stringify({ name: 'John Doe' }),
                person_mode: 'full',
            }

            const result = convertClickhouseRawEventToFilterGlobals(rawEvent)

            expect(result.person).toEqual({
                id: 'person_123',
                properties: { name: 'John Doe' },
            })
            expect(result.pdi).toEqual({
                distinct_id: 'user_123',
                person_id: 'person_123',
                person: {
                    id: 'person_123',
                    properties: { name: 'John Doe' },
                },
            })
        })

        it('should handle group data from RawClickHouseEvent', () => {
            const rawEvent: RawClickHouseEvent = {
                uuid: 'event_uuid',
                event: 'test_event',
                team_id: 1,
                distinct_id: 'user_123',
                project_id: 1 as ProjectId,
                timestamp: '2025-01-01T00:00:00.000Z' as ClickHouseTimestamp,
                created_at: '2025-01-01T00:00:00.000Z' as ClickHouseTimestamp,
                properties: JSON.stringify({ $group_0: 'org_123', $group_1: 'proj_456' }),
                elements_chain: '',
                group0_properties: JSON.stringify({ name: 'Acme Corp' }),
                group1_properties: JSON.stringify({ name: 'Project X' }),
                person_mode: 'full',
            }

            const result = convertClickhouseRawEventToFilterGlobals(rawEvent)

            expect(result.$group_0).toBe('org_123')
            expect(result.$group_1).toBe('proj_456')
            expect(result.$group_2).toBeNull()
            expect(result.$group_3).toBeNull()
            expect(result.$group_4).toBeNull()

            expect(result.group_0).toEqual({ properties: { name: 'Acme Corp' } })
            expect(result.group_1).toEqual({ properties: { name: 'Project X' } })
            expect(result.group_2).toEqual({ properties: {} })
            expect(result.group_3).toEqual({ properties: {} })
            expect(result.group_4).toEqual({ properties: {} })
        })

        it('should handle ClickHouse timestamp conversion', () => {
            const rawEvent: RawClickHouseEvent = {
                uuid: 'event_uuid',
                event: 'test_event',
                team_id: 1,
                distinct_id: 'user_123',
                project_id: 1 as ProjectId,
                timestamp: '2025-01-01 00:00:00.000000' as ClickHouseTimestamp,
                created_at: '2025-01-01T00:00:00.000Z' as ClickHouseTimestamp,
                properties: JSON.stringify({}),
                elements_chain: '',
                person_mode: 'full',
            }

            const result = convertClickhouseRawEventToFilterGlobals(rawEvent)

            expect(result.timestamp).toBe('2025-01-01T00:00:00.000Z')
        })

        it('should handle elements_chain parsing with lazy evaluation', () => {
            const rawEvent: RawClickHouseEvent = {
                uuid: 'event_uuid',
                event: 'test_event',
                team_id: 1,
                distinct_id: 'user_123',
                project_id: 1 as ProjectId,
                timestamp: '2025-01-01T00:00:00.000Z' as ClickHouseTimestamp,
                created_at: '2025-01-01T00:00:00.000Z' as ClickHouseTimestamp,
                properties: JSON.stringify({}),
                elements_chain: 'a:href="https://example.com":text="Click me":attr_id="button1";button',
                person_mode: 'full',
            }

            const result = convertClickhouseRawEventToFilterGlobals(rawEvent)

            expect(result.elements_chain_href).toBe('https://example.com')
            expect(result.elements_chain_texts).toEqual(['Click me'])
            expect(result.elements_chain_ids).toEqual(['button1'])
            expect(result.elements_chain_elements).toEqual(['a', 'button'])
        })
    })
})
