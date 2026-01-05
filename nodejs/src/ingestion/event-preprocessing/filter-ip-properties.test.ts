import { Message } from 'node-rdkafka'

import { EventHeaders, IncomingEventWithTeam, PipelineEvent, ProjectId, Team } from '../../types'
import { isOkResult, ok } from '../pipelines/results'
import { createFilterIpPropertiesStep } from './filter-ip-properties'

describe('createFilterIpPropertiesStep', () => {
    const step = createFilterIpPropertiesStep()

    const createMockTeam = (anonymize_ips: boolean): Team => ({
        id: 1,
        uuid: 'test-uuid',
        organization_id: 'org-1',
        name: 'Test Team',
        anonymize_ips,
        api_token: 'test-token',
        slack_incoming_webhook: null,
        session_recording_opt_in: false,
        person_processing_opt_out: null,
        heatmaps_opt_in: null,
        ingested_event: true,
        person_display_name_properties: null,
        test_account_filters: null,
        cookieless_server_hash_mode: null,
        timezone: 'UTC',
        project_id: 1 as ProjectId,
        available_features: [],
        drop_events_older_than_seconds: null,
    })

    const createMockMessage = (): Message => ({
        value: Buffer.from(''),
        size: 0,
        topic: 'test-topic',
        offset: 0,
        partition: 0,
        timestamp: Date.now(),
    })

    const createMockHeaders = (): EventHeaders => ({
        token: 'test-token',
        distinct_id: 'user123',
        force_disable_person_processing: false,
        historical_migration: false,
    })

    const createMockPipelineEvent = (properties?: Record<string, unknown>): PipelineEvent => ({
        event: '$pageview',
        distinct_id: 'user123',
        team_id: 1,
        uuid: '123e4567-e89b-12d3-a456-426614174000',
        ip: '127.0.0.1',
        site_url: 'https://example.com',
        now: '2021-01-01T00:00:00Z',
        token: 'test-token',
        properties,
    })

    const createMockIncomingEventWithTeam = (
        team: Team,
        properties?: Record<string, unknown>
    ): IncomingEventWithTeam => ({
        event: createMockPipelineEvent(properties),
        team,
        message: createMockMessage(),
        headers: createMockHeaders(),
    })

    describe('when anonymize_ips is enabled', () => {
        it('should remove only $ip and preserve all other properties', async () => {
            const team = createMockTeam(true)
            const input = {
                eventWithTeam: createMockIncomingEventWithTeam(team, {
                    $ip: '192.168.1.1',
                    $browser: 'Chrome',
                    $current_url: 'https://example.com/page',
                    $screen_height: 1080,
                    $screen_width: 1920,
                    $set: { email: 'user@example.com' },
                    $set_once: { initial_referrer: 'google.com' },
                    custom_prop: 'value',
                    nested_obj: { foo: 'bar' },
                }),
            }

            const result = await step(input)

            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                const properties = result.value.eventWithTeam.event.properties
                // Should remove only $ip
                expect(properties).not.toHaveProperty('$ip')
                // Should preserve all other properties
                expect(properties?.$browser).toBe('Chrome')
                expect(properties?.$current_url).toBe('https://example.com/page')
                expect(properties?.$screen_height).toBe(1080)
                expect(properties?.$screen_width).toBe(1920)
                expect(properties?.$set).toEqual({ email: 'user@example.com' })
                expect(properties?.$set_once).toEqual({ initial_referrer: 'google.com' })
                expect(properties?.custom_prop).toBe('value')
                expect(properties?.nested_obj).toEqual({ foo: 'bar' })
                // Should have exactly 8 properties (9 original - 1 removed $ip)
                expect(Object.keys(properties || {})).toHaveLength(8)
            }
        })

        it('should handle events without properties', async () => {
            const team = createMockTeam(true)
            const input = {
                eventWithTeam: createMockIncomingEventWithTeam(team),
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })

        it('should handle events with properties but no $ip', async () => {
            const team = createMockTeam(true)
            const input = {
                eventWithTeam: createMockIncomingEventWithTeam(team, {
                    $browser: 'Chrome',
                }),
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
        })
    })

    describe('when anonymize_ips is disabled', () => {
        it('should preserve all properties including $ip', async () => {
            const team = createMockTeam(false)
            const input = {
                eventWithTeam: createMockIncomingEventWithTeam(team, {
                    $ip: '192.168.1.1',
                    $browser: 'Chrome',
                    $current_url: 'https://example.com/page',
                    $set: { email: 'user@example.com' },
                    custom_prop: 'value',
                }),
            }

            const result = await step(input)

            expect(result).toEqual(ok(input))
            expect(isOkResult(result)).toBe(true)
            if (isOkResult(result)) {
                const properties = result.value.eventWithTeam.event.properties
                // Should keep all properties including $ip
                expect(properties?.$ip).toBe('192.168.1.1')
                expect(properties?.$browser).toBe('Chrome')
                expect(properties?.$current_url).toBe('https://example.com/page')
                expect(properties?.$set).toEqual({ email: 'user@example.com' })
                expect(properties?.custom_prop).toBe('value')
                // Should have exactly 5 properties (none removed)
                expect(Object.keys(properties || {})).toHaveLength(5)
            }
        })
    })
})
