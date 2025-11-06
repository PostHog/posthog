import { Message } from 'node-rdkafka'

import { IncomingEventWithTeam } from '../../types'
import { PipelineResult, ok, redirect } from '../pipelines/results'
import { MemoryRateLimiter } from '../utils/overflow-detector'

export function createRateLimitToOverflowStep<T extends { message: Message; eventWithTeam: IncomingEventWithTeam }>(
    overflowRateLimiter: MemoryRateLimiter,
    overflowEnabled: boolean,
    overflowTopic: string,
    preservePartitionLocality: boolean
) {
    return async function rateLimitToOverflowStep(inputs: T[]): Promise<PipelineResult<T>[]> {
        if (!overflowEnabled) {
            // Overflow disabled, return all events as-is
            return inputs.map((input) => ok(input))
        }

        // Group events by token:distinct_id to count them
        const eventsByKey = new Map<string, Array<T>>()

        for (const input of inputs) {
            const token = input.eventWithTeam.event.token ?? ''
            const distinctId = input.eventWithTeam.event.distinct_id ?? ''
            const eventKey = `${token}:${distinctId}`

            if (!eventsByKey.has(eventKey)) {
                eventsByKey.set(eventKey, [])
            }
            eventsByKey.get(eventKey)!.push(input)
        }

        // Check rate limiter for each key
        const shouldRedirectKey = new Map<string, boolean>()

        for (const [eventKey, events] of eventsByKey) {
            const kafkaTimestamp = events[0].message.timestamp
            const isBelowRateLimit = overflowRateLimiter.consume(eventKey, events.length, kafkaTimestamp)
            shouldRedirectKey.set(eventKey, !isBelowRateLimit)
        }

        // Build results in original order
        return Promise.resolve(
            inputs.map((input) => {
                const token = input.eventWithTeam.event.token ?? ''
                const distinctId = input.eventWithTeam.event.distinct_id ?? ''
                const eventKey = `${token}:${distinctId}`

                if (shouldRedirectKey.get(eventKey)) {
                    return redirect('rate_limit_exceeded', overflowTopic, preservePartitionLocality)
                } else {
                    return ok(input)
                }
            })
        )
    }
}
