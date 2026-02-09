import { DateTime } from 'luxon'
import { v4 } from 'uuid'

import { PipelineResultType, isDropResult } from '../pipelines/results'
import { DropOldEventsInput, createDropOldEventsStep } from './drop-old-events-step'

const createTestInput = (dropThreshold: number | null, eventAgeSeconds: number): DropOldEventsInput => {
    const now = DateTime.utc()
    const eventTimestamp = now.minus({ seconds: eventAgeSeconds })
    const eventUuid = v4()

    return {
        eventWithTeam: {
            event: {
                uuid: eventUuid,
                event: '$pageview',
                distinct_id: 'user-1',
            },
            team: {
                id: 1,
                drop_events_older_than_seconds: dropThreshold,
            },
        },
        headers: {
            timestamp: eventTimestamp.toMillis().toString(),
            now: now.toJSDate(),
        },
    } as DropOldEventsInput
}

describe('createDropOldEventsStep', () => {
    const dropOldEventsStep = createDropOldEventsStep()

    it.each([
        { dropThreshold: null, eventAgeSeconds: 7200, description: 'threshold is null' },
        { dropThreshold: 0, eventAgeSeconds: 7200, description: 'threshold is 0' },
        { dropThreshold: 3600, eventAgeSeconds: 1800, description: 'event is younger than threshold' },
        { dropThreshold: 3600, eventAgeSeconds: 3600, description: 'event is exactly at threshold' },
        { dropThreshold: 3600, eventAgeSeconds: -3600, description: 'event is in the future' },
    ])('passes through event when $description', async ({ dropThreshold, eventAgeSeconds }) => {
        const input = createTestInput(dropThreshold, eventAgeSeconds)

        const result = await dropOldEventsStep(input)

        expect(result.type).toBe(PipelineResultType.OK)
    })

    it('drops event older than threshold with warning', async () => {
        const input = createTestInput(3600, 7200) // threshold: 1h, age: 2h

        const result = await dropOldEventsStep(input)

        expect(result.type).toBe(PipelineResultType.DROP)
        expect(isDropResult(result) && result.reason).toBe('event_too_old')
        expect(result.warnings).toHaveLength(1)
        expect(result.warnings[0]).toMatchObject({
            type: 'event_dropped_too_old',
            details: {
                eventUuid: input.eventWithTeam.event.uuid,
                event: '$pageview',
                distinctId: 'user-1',
                dropThresholdSeconds: 3600,
            },
            alwaysSend: false,
        })
        expect(result.warnings[0].details.ageInSeconds).toBeGreaterThanOrEqual(7199)
    })

    it('passes through when timestamp header is missing', async () => {
        const input = {
            eventWithTeam: {
                event: {
                    uuid: v4(),
                    event: '$pageview',
                    distinct_id: 'user-1',
                },
                team: {
                    id: 1,
                    drop_events_older_than_seconds: 3600,
                },
            },
            headers: {
                now: new Date(),
            },
        } as DropOldEventsInput

        const result = await dropOldEventsStep(input)

        expect(result.type).toBe(PipelineResultType.OK)
    })

    it('uses current time when now header is missing', async () => {
        const now = DateTime.utc()
        const eventTimestamp = now.minus({ hours: 2 }) // 2h old

        const input = {
            eventWithTeam: {
                event: {
                    uuid: v4(),
                    event: '$pageview',
                    distinct_id: 'user-1',
                },
                team: {
                    id: 1,
                    drop_events_older_than_seconds: 3600, // 1h threshold
                },
            },
            headers: {
                timestamp: eventTimestamp.toMillis().toString(),
                // now is missing - should use current time
            },
        } as DropOldEventsInput

        const result = await dropOldEventsStep(input)

        // Event should be dropped based on timestamp vs current time
        expect(result.type).toBe(PipelineResultType.DROP)
    })

    it('uses timestamp from headers (already normalized by Rust capture service)', async () => {
        const now = DateTime.utc()
        // Timestamp header is set to 2h ago by capture service (after clock skew correction)
        const normalizedTimestamp = now.minus({ hours: 2 })

        const input = {
            eventWithTeam: {
                event: {
                    uuid: v4(),
                    event: '$pageview',
                    distinct_id: 'user-1',
                    // Event body timestamp is irrelevant - we use header
                    timestamp: now.minus({ minutes: 1 }).toISO()!,
                },
                team: {
                    id: 1,
                    drop_events_older_than_seconds: 3600, // 1h threshold
                },
            },
            headers: {
                // Capture service already normalized this with clock skew correction
                timestamp: normalizedTimestamp.toMillis().toString(),
                now: now.toJSDate(),
            },
        } as DropOldEventsInput

        const result = await dropOldEventsStep(input)

        // Event should be dropped based on header timestamp (2h old), not event body (1m old)
        expect(result.type).toBe(PipelineResultType.DROP)
    })

    describe('robustness to invalid data', () => {
        it.each([
            { headers: undefined, description: 'headers is undefined' },
            { headers: null, description: 'headers is null' },
        ])('passes through when $description', async ({ headers }) => {
            const input = {
                eventWithTeam: {
                    event: {
                        uuid: v4(),
                        event: '$pageview',
                        distinct_id: 'user-1',
                    },
                    team: {
                        id: 1,
                        drop_events_older_than_seconds: 3600,
                    },
                },
                headers,
            } as unknown as DropOldEventsInput

            const result = await dropOldEventsStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
        })

        it.each([
            { timestamp: 'not-a-number', description: 'timestamp is not a number' },
            { timestamp: '', description: 'timestamp is empty string' },
            { timestamp: 'NaN', description: 'timestamp parses to NaN' },
            { timestamp: 'Infinity', description: 'timestamp parses to Infinity' },
            { timestamp: '-Infinity', description: 'timestamp parses to -Infinity' },
        ])('passes through when $description', async ({ timestamp }) => {
            const input = {
                eventWithTeam: {
                    event: {
                        uuid: v4(),
                        event: '$pageview',
                        distinct_id: 'user-1',
                    },
                    team: {
                        id: 1,
                        drop_events_older_than_seconds: 3600,
                    },
                },
                headers: {
                    timestamp,
                    now: new Date(),
                },
            } as DropOldEventsInput

            const result = await dropOldEventsStep(input)

            expect(result.type).toBe(PipelineResultType.OK)
        })

        it.each([
            { now: new Date('invalid'), description: 'now is invalid Date' },
            { now: 'not-a-date', description: 'now is a string' },
            { now: 12345, description: 'now is a number' },
            { now: {}, description: 'now is an object' },
        ])('uses current time when $description', async ({ now }) => {
            const currentTime = DateTime.utc()
            const eventTimestamp = currentTime.minus({ hours: 2 })

            const input = {
                eventWithTeam: {
                    event: {
                        uuid: v4(),
                        event: '$pageview',
                        distinct_id: 'user-1',
                    },
                    team: {
                        id: 1,
                        drop_events_older_than_seconds: 3600,
                    },
                },
                headers: {
                    timestamp: eventTimestamp.toMillis().toString(),
                    now,
                },
            } as unknown as DropOldEventsInput

            const result = await dropOldEventsStep(input)

            // Should still drop because it falls back to current time
            expect(result.type).toBe(PipelineResultType.DROP)
        })
    })
})
