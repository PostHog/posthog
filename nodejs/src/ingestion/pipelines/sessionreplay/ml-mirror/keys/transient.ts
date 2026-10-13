const TRANSIENT_ERRORS = new Set([
    'ProvisionedThroughputExceededException',
    'ThrottlingException',
    'RequestLimitExceeded',
    'InternalServerError',
    'ServiceUnavailableException',
    'TransactionConflictException',
    'KMSInternalException',
    'DependencyTimeoutException',
    'TimeoutError',
    'AbortError',
])
const TRANSIENT_ERROR_CODES = new Set(['ECONNRESET', 'ECONNREFUSED', 'EPIPE', 'ETIMEDOUT', 'EAI_AGAIN'])

export function isTransientError(error: unknown): boolean {
    if (!(error instanceof Error)) {
        return false
    }
    const { code, $retryable, $fault } = error as Error & { code?: string; $retryable?: unknown; $fault?: string }
    return (
        TRANSIENT_ERRORS.has(error.name) ||
        TRANSIENT_ERROR_CODES.has(code ?? '') ||
        $retryable !== undefined ||
        $fault === 'server'
    )
}
