import { CODES } from 'node-rdkafka'

import { DependencyUnavailableError } from '~/common/utils/db/error'

/** librdkafka codes that a replay of the same message cannot fix. */
const PER_MESSAGE_KAFKA_ERROR_CODES: ReadonlySet<number> = new Set([
    CODES.ERRORS.ERR_INVALID_MSG,
    CODES.ERRORS.ERR_INVALID_MSG_SIZE,
    CODES.ERRORS.ERR_MSG_SIZE_TOO_LARGE,
    CODES.ERRORS.ERR_RECORD_LIST_TOO_LARGE,
    CODES.ERRORS.ERR_INVALID_RECORD,
    CODES.ERRORS.ERR__BAD_MSG,
    CODES.ERRORS.ERR__INVALID_ARG,
    CODES.ERRORS.ERR__INVALID_TYPE,
])

function isLibrdKafkaError(error: unknown): error is Error & { code: number; origin: string } {
    if (typeof error !== 'object' || error === null) {
        return false
    }
    const { code, origin } = error as { code?: unknown; origin?: unknown }
    return typeof code === 'number' && (origin === 'kafka' || origin === 'local')
}

/** node-rdkafka never marks a delivery error as retriable, so an outage would DLQ good data. Raise
 * it as a dependency error so the batch replays; errors a replay cannot fix still go to the DLQ. */
export async function produceLogsOrDependencyError<T>(produce: () => Promise<T>): Promise<T> {
    try {
        return await produce()
    } catch (error) {
        if (isLibrdKafkaError(error) && !PER_MESSAGE_KAFKA_ERROR_CODES.has(error.code)) {
            throw new DependencyUnavailableError(error.message, 'Kafka', error)
        }
        throw error
    }
}
