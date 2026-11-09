import { CODES } from 'node-rdkafka'

import { DependencyUnavailableError } from '~/common/utils/db/error'

const { err2str } = require('node-rdkafka/librdkafka') as { err2str: (code: number) => string }

const PER_MESSAGE_KAFKA_ERROR_CODES: readonly number[] = [
    CODES.ERRORS.ERR_INVALID_MSG,
    CODES.ERRORS.ERR_INVALID_MSG_SIZE,
    CODES.ERRORS.ERR_MSG_SIZE_TOO_LARGE,
    CODES.ERRORS.ERR_RECORD_LIST_TOO_LARGE,
    CODES.ERRORS.ERR_INVALID_RECORD,
    CODES.ERRORS.ERR__BAD_MSG,
    CODES.ERRORS.ERR__INVALID_ARG,
    CODES.ERRORS.ERR__INVALID_TYPE,
]

const librdkafkaText = (message: string): string => message.split(': ').pop()!.toLowerCase()

// A delivery report carries only librdkafka's text, which node-rdkafka parses into `code: -1`.
const PER_MESSAGE_KAFKA_ERROR_TEXTS = new Set(
    PER_MESSAGE_KAFKA_ERROR_CODES.map((code) => librdkafkaText(err2str(code)))
)

type LibrdKafkaError = Error & { code: number; origin: string }

function isLibrdKafkaError(error: unknown): error is LibrdKafkaError {
    if (typeof error !== 'object' || error === null) {
        return false
    }
    const { code, origin } = error as { code?: unknown; origin?: unknown }
    return typeof code === 'number' && (origin === 'kafka' || origin === 'local' || origin === 'broker')
}

function isPerMessageKafkaError(error: LibrdKafkaError): boolean {
    return (
        PER_MESSAGE_KAFKA_ERROR_CODES.includes(error.code) ||
        PER_MESSAGE_KAFKA_ERROR_TEXTS.has(librdkafkaText(error.message))
    )
}

/** node-rdkafka never marks a delivery error as retriable; raise an outage as one so the batch replays. */
export function rethrowKafkaOutageAsDependency(error: unknown): never {
    if (isLibrdKafkaError(error) && !isPerMessageKafkaError(error)) {
        throw new DependencyUnavailableError(error.message, 'Kafka', error)
    }
    throw error
}
