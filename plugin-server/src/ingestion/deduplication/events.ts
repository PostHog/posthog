import { IncomingEvent } from '~/types'
import { logger } from '~/utils/logger'

import { DeduplicationRedis } from './redis-client'

export async function deduplicateEvents(
    deduplicationRedis: DeduplicationRedis,
    messages: IncomingEvent[]
): Promise<void> {
    try {
        if (!messages.length) {
            return
        }

        // Extract event UUIDs for deduplication
        const eventIds = extractEventIds(messages)

        if (!eventIds.length) {
            return
        }

        // Perform fire-and-forget deduplication
        await deduplicationRedis.deduplicate({
            keys: eventIds,
        })
    } catch (error) {
        // Log error but don't fail the batch processing
        logger.warn('Failed to deduplicate events', { error, eventsCount: messages.length })
    }
}

function extractEventIds(messages: IncomingEvent[]): string[] {
    return messages.map(({ event }) => event.uuid).filter((uuid): uuid is string => typeof uuid === 'string')
}
