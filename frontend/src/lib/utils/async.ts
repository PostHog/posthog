export function makeDelay(ms: number): () => Promise<void> {
    return () => delay(ms)
}

export function delay(ms: number, signal?: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
        const timeoutId = setTimeout(resolve, ms)
        if (signal) {
            signal.addEventListener('abort', () => {
                clearTimeout(timeoutId)
                reject(new DOMException('Aborted', 'AbortError'))
            })
        }
    })
}

export interface RetryOptions {
    /** Maximum number of attempts before giving up. Defaults to 3. */
    maxAttempts?: number
    /** Initial delay in milliseconds before the first retry. Defaults to 1000. */
    initialDelayMs?: number
    /** Multiplier applied to delay after each failed attempt. Defaults to 1.5. */
    backoffMultiplier?: number
    /** AbortSignal to cancel retries. If aborted, throws AbortError immediately. */
    signal?: AbortSignal
    /**
     * Predicate to determine if an error should trigger a retry.
     * Return true to retry, false to throw immediately.
     * Defaults to retrying all errors except AbortError.
     *
     * @example
     * // Only retry network errors and 5xx server errors
     * shouldRetry: (error) => {
     *     if (error instanceof Error && 'status' in error) {
     *         const status = (error as any).status
     *         return status >= 500 || status === 0 // 0 = network error
     *     }
     *     return true // retry unknown errors
     * }
     */
    shouldRetry?: (error: unknown) => boolean
}

/**
 * Retries a function with exponential backoff on failure.
 *
 * @param fn - The async function to retry
 * @param options - Configuration options for retry behavior
 * @returns The result of the function if successful
 * @throws The last error encountered if all attempts fail, or AbortError if cancelled
 *
 * @example
 * const data = await retryWithBackoff(() => api.fetchData(), {
 *     maxAttempts: 3,
 *     initialDelayMs: 1000,
 *     backoffMultiplier: 1.5
 * })
 * // Delays: 1000ms after 1st failure, 1500ms after 2nd failure
 */
export async function retryWithBackoff<T>(fn: () => Promise<T>, options: RetryOptions = {}): Promise<T> {
    const { maxAttempts = 3, initialDelayMs = 1000, backoffMultiplier = 1.5, signal, shouldRetry } = options

    if (signal?.aborted) {
        throw new DOMException('Aborted', 'AbortError')
    }

    const attempts = Math.max(maxAttempts, 1)

    let lastError: unknown
    for (let attempt = 0; attempt < attempts; attempt++) {
        try {
            return await fn()
        } catch (e) {
            if (e instanceof DOMException && e.name === 'AbortError') {
                throw e
            }
            lastError = e
            const isLastAttempt = attempt >= attempts - 1
            const canRetry = shouldRetry ? shouldRetry(e) : true
            if (isLastAttempt || !canRetry) {
                throw e
            }
            const delayMs = initialDelayMs * Math.pow(backoffMultiplier, attempt)
            await delay(delayMs, signal)
        }
    }
    throw lastError
}

export function promiseResolveReject<T>(): {
    resolve: (value: T) => void
    reject: (reason?: any) => void
    promise: Promise<T>
} {
    let resolve: (value: T) => void
    let reject: (reason?: any) => void
    const promise = new Promise<T>((innerResolve, innerReject) => {
        resolve = innerResolve
        reject = innerReject
    })
    return { resolve: resolve!, reject: reject!, promise }
}

export function debounce<F extends (...args: Parameters<F>) => ReturnType<F>>(
    func: F,
    waitFor: number
): (...args: Parameters<F>) => void {
    let timeout: ReturnType<typeof setTimeout>
    return (...args: Parameters<F>): void => {
        clearTimeout(timeout)
        timeout = setTimeout(() => func(...args), waitFor)
    }
}
