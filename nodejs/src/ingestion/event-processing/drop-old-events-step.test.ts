import { DateTime } from 'luxon'
import { v4 } from 'uuid'

import { PipelineResultType, isDropResult } from '../pipelines/results'
import { createDropOldEventsStep } from './drop-old-events-step'
import { EventPipelineRunnerInput } from './event-pipeline-runner-v1-step'

const createTestInput = (dropThreshold: number | null, eventAgeSeconds: number): EventPipelineRunnerInput => {
    const now = DateTime.utc()
    const eventUuid = v4()

    return {
        event: {
            uuid: eventUuid,
            event: '$pageview',
            distinct_id: 'user-1',
            now: now.toISO()!,
            timestamp: now.minus({ seconds: eventAgeSeconds }).toISO()!,
        },
        team: {
            id: 1,
            drop_events_older_than_seconds: dropThreshold,
        },
    } as EventPipelineRunnerInput
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
                eventUuid: input.event.uuid,
                event: '$pageview',
                distinctId: 'user-1',
                dropThresholdSeconds: 3600,
            },
            alwaysSend: false,
        })
        expect(result.warnings[0].details.ageInSeconds).toBeGreaterThanOrEqual(7199)
    })

    it('ignores sent_at and uses timestamp (normalization done in Rust)', async () => {
        const now = DateTime.utc()
        const input = {
            event: {
                uuid: v4(),
                event: '$pageview',
                distinct_id: 'user-1',
                now: now.toISO()!,
                timestamp: now.minus({ hours: 2 }).toISO()!, // 2h old - should be dropped
                sent_at: now.minus({ minutes: 1 }).toISO()!, // recent - would pass if used
            },
            team: {
                id: 1,
                drop_events_older_than_seconds: 3600, // 1h threshold
            },
        } as EventPipelineRunnerInput

        const result = await dropOldEventsStep(input)

        // Event should be dropped based on timestamp, not sent_at
        expect(result.type).toBe(PipelineResultType.DROP)
    })
})
