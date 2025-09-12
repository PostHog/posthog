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
        it('handles events with sent_at timestamp', async () => {
            const team = createTeamWithDropSetting(3600) // 1 hour threshold

            // Test events with sent_at that should pass through (adjusted age under 1 hour)
            const eventsThatShouldPass = [
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:00:00.000Z',
                    sent_at: '2024-01-15T11:30:00.000Z',
                    eventType: 'sent_at_30min_timestamp_1h',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T10:00:00.000Z',
                    sent_at: '2024-01-15T11:00:00.000Z',
                    eventType: 'sent_at_1h_timestamp_2h',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:00:00.000Z',
                    sent_at: '2024-01-15T11:01:00.000Z',
                    eventType: 'sent_at_59min_timestamp_1h',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T10:59:50.000Z',
                    sent_at: '2024-01-15T11:00:00.000Z',
                    eventType: 'sent_at_1h_timestamp_1h_minus_10s',
                }),
            ]

            for (const event of eventsThatShouldPass) {
                const result = await dropOldEventsStep(mockRunner, event, team)
                expect(result).toEqual(event)
            }

            // Test events with sent_at that should be dropped (adjusted age 1 hour or older)
            const eventsThatShouldBeDropped = [
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T09:59:59.000Z',
                    sent_at: '2024-01-15T11:00:00.000Z',
                    eventType: 'sent_at_2h1s_timestamp_1h',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T09:00:00.000Z',
                    sent_at: '2024-01-15T11:00:00.000Z',
                    eventType: 'sent_at_3h_timestamp_1h',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T08:00:00.000Z',
                    sent_at: '2024-01-15T11:00:00.000Z',
                    eventType: 'sent_at_4h_timestamp_1h',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-14T12:00:00.000Z',
                    sent_at: '2024-01-15T11:00:00.000Z',
                    eventType: 'sent_at_1day_timestamp_1h',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-10T12:00:00.000Z',
                    sent_at: '2024-01-15T11:00:00.000Z',
                    eventType: 'sent_at_5days_timestamp_1h',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2023-12-15T12:00:00.000Z',
                    sent_at: '2024-01-15T11:00:00.000Z',
                    eventType: 'sent_at_1month_timestamp_1h',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2022-01-15T12:00:00.000Z',
                    sent_at: '2024-01-15T11:00:00.000Z',
                    eventType: 'sent_at_2years_timestamp_1h',
                }),
            ]

            for (const event of eventsThatShouldBeDropped) {
                const result = await dropOldEventsStep(mockRunner, event, team)
                expect(result).toBeNull()
            }
        })

        it('handles events with offset', async () => {
            const team = createTeamWithDropSetting(86400) // 1 day threshold

            // Test events with offset that should pass through (under 1 day old)
            const eventsThatShouldPass = [
                createEvent({ now: '2024-01-15T12:00:00.000Z', eventType: 'current_time_no_offset' }),
                createEvent({ now: '2024-01-15T12:00:00.000Z', offset: 60000, eventType: 'offset_1min' }), // 1 minute old
                createEvent({ now: '2024-01-15T12:00:00.000Z', offset: 3600000, eventType: 'offset_1h' }), // 1 hour old
                createEvent({ now: '2024-01-15T12:00:00.000Z', offset: 43200000, eventType: 'offset_12h' }), // 12 hours old
                createEvent({ now: '2024-01-15T12:00:00.000Z', offset: 86399000, eventType: 'offset_just_under_1day' }), // 23:59:59 old
            ]

            for (const event of eventsThatShouldPass) {
                const result = await dropOldEventsStep(mockRunner, event, team)
                expect(result).toEqual(event)
            }

            // Test events with offset that should be dropped (1 day old or older)
            const eventsThatShouldBeDropped = [
                createEvent({ now: '2024-01-15T12:00:00.000Z', offset: 86401000, eventType: 'offset_just_over_1day' }), // 1:00:01 old
                createEvent({ now: '2024-01-15T12:00:00.000Z', offset: 172800000, eventType: 'offset_2days' }), // 2 days old
                createEvent({ now: '2024-01-15T12:00:00.000Z', offset: 604800000, eventType: 'offset_1week' }), // 1 week old
                createEvent({ now: '2024-01-15T12:00:00.000Z', offset: 2592000000, eventType: 'offset_30days' }), // 30 days old
                createEvent({ now: '2024-01-15T12:00:00.000Z', offset: 31536000000, eventType: 'offset_1year' }), // 1 year old
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

        it('handles invalid timestamps, offsets, and sent_at gracefully', async () => {
            const team = createTeamWithDropSetting(3600) // 1 hour threshold

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

            for (const event of invalidTimestampEvents) {
                const result = await dropOldEventsStep(mockRunner, event, team)
                expect(result).toEqual(event)
            }

            const invalidOffsetEvents = [
                createEvent({ now: '2024-01-15T12:00:00.000Z', offset: NaN, eventType: 'invalid_offset_nan' }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    offset: Infinity,
                    eventType: 'invalid_offset_infinity',
                }),
                createEvent({ now: '2024-01-15T12:00:00.000Z', offset: -1, eventType: 'invalid_offset_negative' }),
            ]

            for (const event of invalidOffsetEvents) {
                const result = await dropOldEventsStep(mockRunner, event, team)
                expect(result).toEqual(event)
            }

            const invalidSentAtEvents = [
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:00:00.000Z',
                    sent_at: 'invalid-sent-at',
                    eventType: 'invalid_sent_at_event',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:00:00.000Z',
                    sent_at: '',
                    eventType: 'empty_sent_at_event',
                }),
                createEvent({
                    now: '2024-01-15T12:00:00.000Z',
                    timestamp: '2024-01-15T11:00:00.000Z',
                    sent_at: '2024-13-45T25:70:99.999Z',
                    eventType: 'invalid_sent_at_date_event',
                }),
            ]

            for (const event of invalidSentAtEvents) {
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
