import crypto from 'crypto'

import { IncomingEvent } from '~/types'
import { logger } from '~/utils/logger'

import { KeyMetricData } from './metrics'
import { DeduplicationRedis } from './redis-client'

export async function deduplicateEvents(
    deduplicationRedis: DeduplicationRedis,
    messages: IncomingEvent[]
): Promise<void> {
    try {
        if (!messages.length) {
            return
        }

        // Extract event deduplication keys and create mapping to messages
        const { keys: deduplicationKeys, keyToMetricDataMap } = extractDeduplicationKeysWithMapping(messages)

        if (!deduplicationKeys.length) {
            return
        }

        // Perform fire-and-forget deduplication
        await deduplicationRedis.deduplicateIds({
            keys: deduplicationKeys,
            keyToMetricDataMap,
        })
    } catch (error) {
        // Log error but don't fail the batch processing
        logger.warn('Failed to deduplicate events', { error, eventsCount: messages.length })
    }
}

function extractDeduplicationKeysWithMapping(messages: IncomingEvent[]): {
    keys: string[]
    keyToMetricDataMap: Map<string, KeyMetricData>
} {
    const keys = new Set<string>()
    const keyToMetricDataMap = new Map<string, KeyMetricData>()
    messages.forEach(({ event }) => {
        // Create a robust deduplication key using (event_name, distinct_id, timestamp, uuid)
        // This prevents gaming the system when SDKs have bugs or apply naive retry strategies
        const { token, event: eventName, distinct_id, timestamp, properties } = event
        const source = properties?.$lib ?? 'unknown'

        // Only create a key if we have all required fields
        if (!token || !eventName || !distinct_id || !timestamp) {
            return null
        }

        // Create a composite key that matches ClickHouse deduplication logic
        // Format: token:event_name:distinct_id:timestamp
        const key = `${token}:${eventName}:${distinct_id}:${timestamp}`
        // Hash the key to prevent it from being too long
        const hashedKey = crypto.createHash('sha256').update(key).digest('hex')
        keys.add(hashedKey)
        keyToMetricDataMap.set(hashedKey, { source })
    })

    return {
        keys: Array.from(keys),
        keyToMetricDataMap,
    }
}
