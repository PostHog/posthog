export class DependencyUnavailableError extends Error {
    constructor(message: string, dependencyName: string, error: Error) {
        super(message)
        this.name = 'DependencyUnavailableError'
        this.dependencyName = dependencyName
        this.error = error
    }
    readonly dependencyName: string
    readonly error: Error
    readonly isRetriable = true
}

export class MessageSizeTooLarge extends Error {
    constructor(message: string, error: Error) {
        super(message)
        this.name = 'MessageSizeTooLarge'
        this.error = error
    }
    readonly error: Error
    readonly isRetriable = false
}

/**
 * The target topic does not exist on the cluster this producer is connected to.
 *
 * Permanent by construction: the topic does not appear because we asked again. A caller must
 * handle the message instead of retrying it, or the same message fails forever.
 */
export class UnknownTopicError extends Error {
    constructor(topic: string, error: Error) {
        super(`Kafka topic "${topic}" does not exist on this cluster`)
        this.name = 'UnknownTopicError'
        this.topic = topic
        this.error = error
    }
    readonly topic: string
    readonly error: Error
    readonly isRetriable = false
}

export class RedisOperationError extends Error {
    constructor(message: string, error: Error, operation: string, logContext?: Record<string, any>) {
        super(message)
        this.name = 'RedisOperationError'
        this.error = error
        this.operation = operation
        this.logContext = logContext
    }
    readonly error: Error
    readonly logContext?: Record<string, any>
    readonly operation: string
}
