import { Counter } from 'prom-client'

import { EventHeaders } from '../../types'
import { logger } from '../../utils/logger'
import { parseDate } from './timestamps'

// Metrics for tracking timestamp header comparisons
const timestampComparisonCounter = new Counter({
    name: 'timestamp_header_comparison_total',
    help: 'Count of timestamp header comparisons by result',
    labelNames: ['result', 'context'],
})

/**
 * Determine if we should log based on sample rate
 */
function shouldSampleLog(sampleRate: number): boolean {
    if (sampleRate <= 0) {
        return false
    }
    if (sampleRate >= 1) {
        return true
    }
    return Math.random() < sampleRate
}

/**
 * Compare timestamp from headers with current parsing logic and log differences
 */
export function compareTimestamps(
    currentTimestamp: string | undefined,
    headers: EventHeaders | undefined,
    teamId: number,
    eventUuid?: string,
    context?: string,
    loggingSampleRate: number = 0.0
): void {
    const contextLabel = context || 'timestamp_comparison'

    if (!currentTimestamp) {
        timestampComparisonCounter
            .labels({
                result: 'event_timestamp_missing',
                context: contextLabel,
            })
            .inc()
        return
    }

    if (!headers?.timestamp) {
        timestampComparisonCounter
            .labels({
                result: 'header_missing',
                context: contextLabel,
            })
            .inc()
        return
    }

    try {
        const headerTimestampMs = parseInt(headers.timestamp, 10)
        if (isNaN(headerTimestampMs)) {
            timestampComparisonCounter
                .labels({
                    result: 'header_invalid',
                    context: contextLabel,
                })
                .inc()
            return
        }

        const headerDate = new Date(headerTimestampMs)
        const currentDate = parseDate(currentTimestamp).toJSDate()

        const headerTime = headerDate.getTime()
        const currentTime = currentDate.getTime()

        if (headerTime === currentTime) {
            timestampComparisonCounter
                .labels({
                    result: 'exact_match',
                    context: contextLabel,
                })
                .inc()
        } else {
            timestampComparisonCounter
                .labels({
                    result: 'difference_detected',
                    context: contextLabel,
                })
                .inc()

            if (shouldSampleLog(loggingSampleRate)) {
                logger.info('Timestamp difference detected', {
                    context: contextLabel,
                    team_id: teamId,
                    event_uuid: eventUuid,
                    current_timestamp: currentTimestamp,
                    header_timestamp_ms: headerTimestampMs,
                    current_parsed: currentDate.toISOString(),
                    header_parsed: headerDate.toISOString(),
                    difference_ms: Math.abs(headerTime - currentTime),
                })
            }
        }
    } catch (error) {
        timestampComparisonCounter
            .labels({
                result: 'parse_error',
                context: contextLabel,
            })
            .inc()

        if (shouldSampleLog(loggingSampleRate)) {
            logger.warn('Failed to compare timestamps', {
                context: contextLabel,
                error: error.message,
                team_id: teamId,
                event_uuid: eventUuid,
                header_timestamp: headers.timestamp,
                current_timestamp: currentTimestamp,
            })
        }
    }
}
