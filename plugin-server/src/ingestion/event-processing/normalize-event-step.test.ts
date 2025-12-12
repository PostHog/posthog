import { DateTime } from 'luxon'
import { v4 } from 'uuid'

import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { PipelineEvent, ProjectId, Team } from '../../types'
import { UUIDT } from '../../utils/utils'
import { PipelineResultType } from '../pipelines/results'
import { createNormalizeEventStep } from './normalize-event-step'

const createTestTeam = (overrides: Partial<Team> = {}): Team => ({
    id: 1,
    project_id: 1 as ProjectId,
    organization_id: 'test-org-id',
    uuid: v4(),
    name: 'Test Team',
    anonymize_ips: false,
    api_token: 'test-api-token',
    slack_incoming_webhook: null,
    session_recording_opt_in: true,
    person_processing_opt_out: null,
    heatmaps_opt_in: null,
    ingested_event: true,
    person_display_name_properties: null,
    test_account_filters: null,
    cookieless_server_hash_mode: null,
    timezone: 'UTC',
    available_features: [],
    drop_events_older_than_seconds: null,
    ...overrides,
})

describe('normalizeEventStep wrapper', () => {
    const timestampComparisonLoggingSampleRate = 0
    const team = createTestTeam()

    describe('distinctId conversion', () => {
        it('converts number distinct_id to string', async () => {
            const uuid = new UUIDT().toString()
            const event: PipelineEvent = {
                distinct_id: 123 as any,
                ip: null,
                site_url: 'http://localhost',
                team_id: team.id,
                now: '2020-02-23T02:15:00Z',
                timestamp: '2020-02-23T02:15:00Z',
                event: 'test event',
                uuid: uuid,
            }

            const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
            const input = {
                event,
                headers: createTestEventHeaders(),
                team,
                processPerson: true,
            }

            const result = await step(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.normalizedEvent.distinct_id).toBe('123')
                expect(typeof result.value.normalizedEvent.distinct_id).toBe('string')
            }
        })

        it('converts boolean distinct_id to string', async () => {
            const uuid = new UUIDT().toString()
            const event: PipelineEvent = {
                distinct_id: true as any,
                ip: null,
                site_url: 'http://localhost',
                team_id: team.id,
                now: '2020-02-23T02:15:00Z',
                timestamp: '2020-02-23T02:15:00Z',
                event: 'test event',
                uuid: uuid,
            }

            const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
            const input = {
                event,
                headers: createTestEventHeaders(),
                team,
                processPerson: true,
            }

            const result = await step(input)

            expect(result.type).toBe(PipelineResultType.OK)
            if (result.type === PipelineResultType.OK) {
                expect(result.value.normalizedEvent.distinct_id).toBe('true')
                expect(typeof result.value.normalizedEvent.distinct_id).toBe('string')
            }
        })
    })

    it('initializes empty properties object when missing', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'test event',
            uuid: uuid,
            // No properties field
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: true,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.normalizedEvent.properties).toBeDefined()
            expect(typeof result.value.normalizedEvent.properties).toBe('object')
        }
    })

    it('sanitizes token with null bytes', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            token: '\u0000token',
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'test event',
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: true,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.normalizedEvent.token).toBe('\uFFFDtoken')
        }
    })

    it('merges $set with priority: root level overrides properties', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'test event',
            properties: {
                $set: { key2: 'value3', key3: 'value4' },
            },
            $set: { key1: 'value1', key2: 'value2' },
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: true,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            // Root level $set should override properties.$set for same keys
            expect(result.value.normalizedEvent.properties!.$set).toEqual({
                key1: 'value1',
                key2: 'value2', // overridden from root level
                key3: 'value4',
            })
        }
    })

    it('merges $set_once with priority: root level overrides properties', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'test event',
            properties: {
                $set_once: { key2_once: 'value3', key3_once: 'value4' },
            },
            $set_once: { key1_once: 'value1', key2_once: 'value2' },
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: true,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            // Root level $set_once should override properties.$set_once for same keys
            expect(result.value.normalizedEvent.properties!.$set_once).toEqual({
                key1_once: 'value1',
                key2_once: 'value2', // overridden from root level
                key3_once: 'value4',
            })
        }
    })

    it('normalizes with processPerson=true and preserves person properties', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'default event',
            properties: {
                $set: {
                    a: 5,
                },
                $browser: 'Chrome',
            },
            $set: {
                someProp: 'value',
            },
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: true,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            // Since processPerson=true, person properties should be preserved and merged
            expect(result.value.normalizedEvent).toEqual({
                ...event,
                properties: {
                    $browser: 'Chrome',
                    $set: {
                        someProp: 'value',
                        a: 5,
                        $browser: 'Chrome',
                    },
                    $set_once: {
                        $initial_browser: 'Chrome',
                    },
                },
            })

            expect(result.value.timestamp).toEqual(DateTime.fromISO(event.timestamp!, { zone: 'utc' }))

            // Verify required fields are present
            expect(result.value.team).toBe(team)
            expect(result.value.headers).toEqual(createTestEventHeaders())

            // Verify event field is removed
            expect('event' in result.value).toBe(false)
        }
    })

    it('replaces null byte with unicode replacement character in distinct_id (processPerson=true)', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: '\u0000foo',
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'default event',
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: true,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.normalizedEvent).toEqual({
                ...event,
                distinct_id: '\uFFFDfoo',
                properties: {},
            })

            expect(result.value.timestamp).toEqual(DateTime.fromISO(event.timestamp!, { zone: 'utc' }))

            // Verify required fields are present
            expect(result.value.team).toBe(team)
            expect(result.value.headers).toEqual(createTestEventHeaders())

            // Verify event field is removed
            expect('event' in result.value).toBe(false)
        }
    })

    it('normalizes events with processPerson=false by dropping person-related properties', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: '$$heatmap',
            properties: {
                $set: {
                    a: 5,
                },
                $set_once: {
                    b: 10,
                },
                $unset: ['c'],
                $browser: 'Chrome',
            },
            $set: {
                someProp: 'value',
            },
            $set_once: {
                foo: 'bar',
            },
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: false,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            // The step always uses processPerson=false, so person-related properties should be dropped
            expect(result.value.normalizedEvent).toEqual({
                ...event,
                // $set and $set_once at root level should be gone
                $set: undefined,
                $set_once: undefined,
                properties: {
                    $browser: 'Chrome',
                    $process_person_profile: false,
                },
            })

            expect(result.value.timestamp).toEqual(DateTime.fromISO(event.timestamp!, { zone: 'utc' }))

            // Verify required fields are present
            expect(result.value.team).toBe(team)
            expect(result.value.headers).toEqual(createTestEventHeaders())

            // Verify event field is removed
            expect('event' in result.value).toBe(false)
        }
    })

    it('merges $set from root level into properties.$set', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'test event',
            properties: {
                $set: {
                    propA: 'valueA',
                },
            },
            $set: {
                propB: 'valueB',
            },
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: true,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            // Root level $set should merge into properties.$set
            expect(result.value.normalizedEvent.properties!.$set).toEqual({
                propA: 'valueA',
                propB: 'valueB',
            })
        }
    })

    it('merges $set_once from root level into properties.$set_once', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'test event',
            properties: {
                $set_once: {
                    onceA: 'valueA',
                },
            },
            $set_once: {
                onceB: 'valueB',
            },
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: true,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            // Root level $set_once should merge into properties.$set_once
            expect(result.value.normalizedEvent.properties!.$set_once).toEqual({
                onceA: 'valueA',
                onceB: 'valueB',
            })
        }
    })

    it('adds $ip from event.ip to properties if not already present', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: '192.168.1.1',
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'test event',
            properties: {},
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: true,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.normalizedEvent.properties!.$ip).toBe('192.168.1.1')
            // ip field should be set to null
            expect(result.value.normalizedEvent.ip).toBe(null)
        }
    })

    it('does not override existing $ip in properties', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: '192.168.1.1',
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'test event',
            properties: {
                $ip: '10.0.0.1',
            },
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: true,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            // Should keep the original $ip from properties
            expect(result.value.normalizedEvent.properties!.$ip).toBe('10.0.0.1')
        }
    })

    it('adds $sent_at to properties from event.sent_at', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            sent_at: '2020-02-23T02:14:00Z',
            event: 'test event',
            properties: {},
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: true,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.normalizedEvent.properties!.$sent_at).toBe('2020-02-23T02:14:00Z')
        }
    })

    it('deletes $unset for processPerson=false', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'test event',
            properties: {
                $unset: ['prop1', 'prop2'],
            },
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: false,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            // $unset should be removed for processPerson=false
            expect(result.value.normalizedEvent.properties!.$unset).toBeUndefined()
        }
    })

    it('handles $groupidentify event with processPerson=true by removing person properties', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: '$groupidentify',
            properties: {
                $set: {
                    a: 5,
                },
            },
            $set: {
                someProp: 'value',
            },
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: true,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            // $groupidentify always has person properties removed
            expect(result.value.normalizedEvent.$set).toBeUndefined()
            expect(result.value.normalizedEvent.properties!.$set).toBeUndefined()
            // But $process_person_profile is not added since processPerson=true
            expect(result.value.normalizedEvent.properties!.$process_person_profile).toBeUndefined()
        }
    })

    it('removes $process_person_profile when processPerson=true', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'test event',
            properties: {
                $process_person_profile: false,
                other: 'value',
            },
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: true,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            // $process_person_profile should be removed when processPerson=true (it's the default)
            expect(result.value.normalizedEvent.properties!.$process_person_profile).toBeUndefined()
            expect(result.value.normalizedEvent.properties!.other).toBe('value')
        }
    })

    it('passes through additional input fields to the output', async () => {
        const uuid = new UUIDT().toString()
        const event: PipelineEvent = {
            distinct_id: 'my_id',
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: 'test event',
            uuid: uuid,
        }

        const step = createNormalizeEventStep(timestampComparisonLoggingSampleRate)
        const input = {
            event,
            headers: createTestEventHeaders(),
            team,
            processPerson: false,
            // Additional fields
            customField: 'custom value',
            anotherField: 123,
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            // Verify additional fields are passed through
            expect((result.value as any).customField).toBe('custom value')
            expect((result.value as any).anotherField).toBe(123)

            // Verify event field is removed
            expect('event' in result.value).toBe(false)

            // Verify normalized fields are added
            expect(result.value.normalizedEvent).toBeDefined()
            expect(result.value.timestamp).toBeDefined()
        }
    })
})
