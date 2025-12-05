import { PluginEvent } from '@posthog/plugin-scaffold'

import { Team } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { dropOldEventsStep } from '../../../../src/worker/ingestion/event-pipeline/dropOldEventsStep'
import { createOrganization, createTeam, resetTestDatabase } from '../../../helpers/sql'

describe('dropOldEventsStep()', () => {
    let hub: any
    let organizationId: string
    let teamId: number
    let mockRunner: any

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        organizationId = await createOrganization(hub.db.postgres)
        teamId = await createTeam(hub.db.postgres, organizationId)

        mockRunner = {
            hub: {
                db: {
                    kafkaProducer: {
                        queueMessages: jest.fn().mockResolvedValue(undefined),
                    },
                },
            },
        }
    })

    const createEvent = ({
        now,
        timestamp,
        sent_at,
        offset,
        eventType = 'test event',
        ...extraProperties
    }: {
        now: string
        timestamp?: string
        sent_at?: string
        offset?: number
        eventType?: string
    } & Partial<PluginEvent>): PluginEvent => ({
        distinct_id: 'my_id',
        ip: '127.0.0.1',
        site_url: 'http://localhost',
        team_id: teamId,
        now,
        timestamp,
        event: eventType,
        properties: {},
        uuid: new UUIDT().toString(),
        ...(sent_at && { sent_at }),
        ...(offset && { offset }),
        ...extraProperties,
    })

    const createTeamWithDropSetting = (dropEventsOlderThan: number | null): Team =>
        ({
            id: teamId,
            drop_events_older_than_seconds: dropEventsOlderThan,
        }) as Team

    describe('basic functionality', () => {
        it('passes through events when no drop threshold is set', async () => {
            const team = createTeamWithDropSetting(null)

            // Test various event ages - all should pass through when no threshold is set
            const events = [
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T12:00:00.000Z',
                    eventType: 'current_time',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:30:00.000Z',
                    eventType: '30_min_old',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T10:00:00.000Z',
                    eventType: '2_hours_old',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-10T12:00:00.000Z',
                    eventType: '5_days_old',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2023-12-15T12:00:00.000Z',
                    eventType: '1_month_old',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2022-01-15T12:00:00.000Z',
                    eventType: '2_years_old',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T13:00:00.000Z',
                    eventType: '1_hour_future',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2020-01-01T00:00:00.000Z',
                    eventType: 'very_old_2020',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2015-06-15T12:30:45.000Z',
                    eventType: 'much_older_2015',
                }),
            ]

            for (const event of events) {
                const result = await dropOldEventsStep(mockRunner, event, team)
                expect(result).toEqual(event)
            }
        })

        it('passes through events that are not too old', async () => {
            const team = createTeamWithDropSetting(3600) // 1 hour threshold

            // Test various events that should pass through (under 1 hour old)
            const eventsThatShouldPass = [
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T12:00:00.000Z',
                    eventType: 'current_time',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:59:00.000Z',
                    eventType: '1_min_old',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:30:00.000Z',
                    eventType: '30_min_old',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:15:00.000Z',
                    eventType: '45_min_old',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:01:00.000Z',
                    eventType: '59_min_old',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:00:01.000Z',
                    eventType: 'just_under_1h',
                }),
            ]

            for (const event of eventsThatShouldPass) {
                const result = await dropOldEventsStep(mockRunner, event, team)
                expect(result).toEqual(event)
            }

            // Test events that should be dropped (1 hour old or older)
            const eventsThatShouldBeDropped = [
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T10:59:59.000Z',
                    eventType: 'just_over_1h',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T10:00:00.000Z',
                    eventType: '2_hours_old',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-14T12:00:00.000Z',
                    eventType: '1_day_old',
                }),
            ]

            for (const event of eventsThatShouldBeDropped) {
                const result = await dropOldEventsStep(mockRunner, event, team)
                expect(result).toBeNull()
            }
        })

        it('ignores zero drop threshold to protect from misconfiguration', async () => {
            const teamZeroThreshold = createTeamWithDropSetting(0)

            const eventsWithDifferentAges = [
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:59:59.000Z',
                    eventType: 'recent_event_zero_threshold',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T10:00:00.000Z',
                    eventType: '2h_old_event_zero_threshold',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-14T12:00:00.000Z',
                    eventType: '1day_old_event_zero_threshold',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2023-12-15T12:00:00.000Z',
                    eventType: '1month_old_event_zero_threshold',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2020-01-01T00:00:00.000Z',
                    eventType: 'very_old_event_zero_threshold',
                }),
            ]

            // Zero threshold is ignored to protect from accidentally dropping all events
            for (const event of eventsWithDifferentAges) {
                const result = await dropOldEventsStep(mockRunner, event, teamZeroThreshold)
                expect(result).toEqual(event)
            }
        })
    })

    describe('timestamp handling', () => {
        it('ignores sent_at and uses already-normalized timestamp from Rust', async () => {
            const team = createTeamWithDropSetting(3600) // 1 hour threshold

            // Note: Timestamp normalization (clock skew with sent_at) is now done in Rust capture service.
            // The timestamp field contains the already-normalized value.
            // sent_at is included in test data but should be ignored by plugin-server.

            // Test events that should pass through (under 1 hour old after normalization)
            const eventsThatShouldPass = [
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:30:00.000Z', // Normalized timestamp: 30 min old
                    sent_at: '2024-01-15T11:00:00.000Z', // This should be IGNORED
                    eventType: 'normalized_30min_old_with_sent_at',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:00:00.000Z', // Normalized timestamp: 1 hour old
                    sent_at: '2024-01-15T10:00:00.000Z', // This should be IGNORED
                    eventType: 'normalized_1h_old_with_sent_at',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:00:01.000Z', // Normalized timestamp: just under 1 hour
                    sent_at: '2024-01-15T09:00:00.000Z', // This should be IGNORED
                    eventType: 'normalized_just_under_1h_with_sent_at',
                }),
            ]

            for (const event of eventsThatShouldPass) {
                const result = await dropOldEventsStep(mockRunner, event, team)
                expect(result).toEqual(event)
            }

            // Test events that should be dropped (over 1 hour old after normalization)
            const eventsThatShouldBeDropped = [
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T10:59:59.000Z', // Normalized timestamp: just over 1 hour
                    sent_at: '2024-01-15T11:30:00.000Z', // This should be IGNORED (would suggest event is recent if used)
                    eventType: 'normalized_just_over_1h_with_sent_at',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T10:00:00.000Z', // Normalized timestamp: 2 hours old
                    sent_at: '2024-01-15T11:45:00.000Z', // This should be IGNORED (would suggest event is recent if used)
                    eventType: 'normalized_2h_old_with_sent_at',
                }),
            ]

            for (const event of eventsThatShouldBeDropped) {
                const result = await dropOldEventsStep(mockRunner, event, team)
                expect(result).toBeNull()
            }
        })

        it('ignores offset and uses already-normalized timestamp from Rust', async () => {
            const team = createTeamWithDropSetting(86400) // 1 day threshold

            // Note: Offset normalization is now done in Rust capture service.
            // The timestamp field contains the already-normalized value (now - offset).
            // offset is included in test data but should be ignored by plugin-server.

            // Test events that should pass through (under 1 day old after normalization)
            const eventsThatShouldPass = [
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:59:00.000Z', // Normalized: 1 min old
                    offset: 3600000, // This should be IGNORED (would suggest 1 hour old if used)
                    eventType: 'normalized_1min_old_with_offset',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T00:00:00.000Z', // Normalized: 12 hours old
                    offset: 86400000, // This should be IGNORED (would suggest 1 day old if used)
                    eventType: 'normalized_12h_old_with_offset',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-14T12:00:01.000Z', // Normalized: just under 1 day
                    offset: 172800000, // This should be IGNORED (would suggest 2 days old if used)
                    eventType: 'normalized_just_under_1day_with_offset',
                }),
            ]

            for (const event of eventsThatShouldPass) {
                const result = await dropOldEventsStep(mockRunner, event, team)
                expect(result).toEqual(event)
            }

            // Test events that should be dropped (1 day old or older after normalization)
            const eventsThatShouldBeDropped = [
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-14T11:59:59.000Z', // Normalized: just over 1 day
                    offset: 60000, // This should be IGNORED (would suggest 1 min old if used)
                    eventType: 'normalized_just_over_1day_with_offset',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-13T12:00:00.000Z', // Normalized: 2 days old
                    offset: 3600000, // This should be IGNORED (would suggest 1 hour old if used)
                    eventType: 'normalized_2days_old_with_offset',
                }),
            ]

            for (const event of eventsThatShouldBeDropped) {
                const result = await dropOldEventsStep(mockRunner, event, team)
                expect(result).toBeNull()
            }
        })

        it('handles events from different days', async () => {
            const team = createTeamWithDropSetting(86400) // 24 hours threshold
            const event = createEvent({
                now: '2024-01-15T12:00:00.000Z',
                timestamp: '2024-01-13T12:00:00.000Z',
                eventType: '2_days_old',
            })

            const result = await dropOldEventsStep(mockRunner, event, team)

            expect(result).toBeNull()
        })

        it('handles events from different months', async () => {
            const team = createTeamWithDropSetting(86400) // 24 hours threshold
            const event = createEvent({
                now: '2024-01-15T12:00:00.000Z',
                timestamp: '2023-12-15T12:00:00.000Z',
                eventType: '1_month_old',
            })

            const result = await dropOldEventsStep(mockRunner, event, team)

            expect(result).toBeNull()
        })

        it('handles events from different years', async () => {
            const team = createTeamWithDropSetting(86400) // 24 hours threshold
            const event = createEvent({
                now: '2024-01-15T12:00:00.000Z',
                timestamp: '2022-01-15T12:00:00.000Z',
                eventType: '2_years_old',
            })

            const result = await dropOldEventsStep(mockRunner, event, team)

            expect(result).toBeNull()
        })

        it('handles future events', async () => {
            const team = createTeamWithDropSetting(3600) // 1 hour threshold

            const futureEvents = [
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T13:00:00.000Z',
                    eventType: 'future_event_1h',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T14:00:00.000Z',
                    eventType: 'future_event_2h',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-16T12:00:00.000Z',
                    eventType: 'future_event_24h',
                }),
            ]

            for (const event of futureEvents) {
                const result = await dropOldEventsStep(mockRunner, event, team)
                expect(result).toEqual(event)
            }
        })

        it('handles invalid timestamps gracefully', async () => {
            const team = createTeamWithDropSetting(3600) // 1 hour threshold

            // Note: Timestamp normalization is done in Rust, but we still need to handle
            // invalid timestamps gracefully in case they slip through.
            // Invalid timestamps should not cause the drop logic to fail - events should pass through.

            const invalidTimestampEvents = [
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: 'invalid-timestamp',
                    eventType: 'invalid_timestamp_event',
                }),
                createEvent({ now: '2024-01-15T12:00:00.000Z', timestamp: '', eventType: 'empty_timestamp_event' }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-13-45T25:70:99.999Z',
                    eventType: 'invalid_date_event',
                }),
            ]

            // Invalid timestamps should be handled gracefully and events should pass through
            for (const event of invalidTimestampEvents) {
                const result = await dropOldEventsStep(mockRunner, event, team)
                expect(result).toEqual(event)
            }
        })
    })

    describe('ingestion warnings', () => {
        beforeEach(() => {
            // Mock the current time to make tests deterministic
            jest.useFakeTimers()
            jest.setSystemTime(new Date('2024-01-15T12:00:00.000Z'))
        })

        afterEach(() => {
            // Restore the real timers
            jest.useRealTimers()
        })

        it('logs ingestion warnings for dropped events', async () => {
            const team = createTeamWithDropSetting(3600) // 1 hour threshold
            const oldEvent = createEvent({
                now: '2024-01-15T12:00:00.000Z',
                timestamp: '2024-01-15T10:00:00.000Z',
                eventType: 'old_event_for_warning',
            })

            const result = await dropOldEventsStep(mockRunner, oldEvent, team)
            expect(result).toBeNull()

            // Verify that the warning was logged via the runner
            expect(mockRunner.hub.db.kafkaProducer.queueMessages).toHaveBeenCalledWith({
                topic: 'clickhouse_ingestion_warnings_test',
                messages: [
                    {
                        value: JSON.stringify({
                            team_id: teamId,
                            type: 'event_dropped_too_old',
                            source: 'plugin-server',
                            details: JSON.stringify({
                                eventUuid: oldEvent.uuid,
                                event: oldEvent.event,
                                distinctId: oldEvent.distinct_id,
                                eventTimestamp: '2024-01-15T10:00:00.000Z',
                                ageInSeconds: 7200, // 2 hours
                                dropThresholdSeconds: 3600,
                            }),
                            timestamp: '2024-01-15 12:00:00.000',
                        }),
                    },
                ],
            })
        })
    })
})
