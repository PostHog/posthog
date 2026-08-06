import { DependencyUnavailableError } from '../utils/db/error'
import { logger } from '../utils/logger'

export const retryOnDependencyUnavailableError = async <T>(
    fn: () => Promise<T>,
    {
        retryCount,
        initialRetryDelayMs,
    }: {
        retryCount: number
        initialRetryDelayMs: number
    } = { retryCount: 5, initialRetryDelayMs: 1000 }
): Promise<T> => {
    // Try processing the message. If we get a
    // DependencyUnavailableError retry up to 5 times starting
    // with a delay of 1 second, then 2 seconds, 4 seconds, 8
    // seconds, and finally 16 seconds. If we still get an error
    // after that, we will throw it and stop processing.
    // If we get any other error, we will throw it and stop
    // processing.
    let currentRetryCount = 0
    let retryDelay = initialRetryDelayMs

    while (currentRetryCount < retryCount) {
        try {
            return await fn()
        } catch (error) {
            if (error instanceof DependencyUnavailableError) {
                if (currentRetryCount === 4) {
                    logger.error('🔁', 'main_loop_error_retry_limit', {
                        error,
                        currentRetryCount,
                        retryDelay,
                    })
                    throw error
                } else {
                    logger.error('🔁', 'main_loop_error_retriable', {
                        error,
                        retryCount,
                        retryDelay,
                    })
                    await new Promise((resolve) => setTimeout(resolve, retryDelay))
                    retryDelay *= 2
                    currentRetryCount += 1
                }
            } else {
                logger.error('🔁', 'main_loop_error', { error })
                throw error
            }
        }
    }

    throw new Error('Should not get here')
}
