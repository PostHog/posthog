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

export class RetryError extends Error {
    /** Set by the system. */
    _attempt: number | undefined
    /** Set by the system. */
    _maxAttempts: number | undefined

    constructor(message?: string) {
        super(message)
        this.name = 'RetryError'
    }

    get nameWithAttempts(): string {
        return this._attempt && this._maxAttempts
            ? `${this.name} (attempt ${this._attempt}/${this._maxAttempts})`
            : this.name
    }

    toString(): string {
        return this.message ? `${this.nameWithAttempts}: ${this.message}` : this.nameWithAttempts
    }
}
