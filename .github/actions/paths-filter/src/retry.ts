export interface RetryOptions {
  // Total number of attempts, including the first one
  attempts: number
  // Delay before the second attempt; doubles on every further retry
  baseDelayMs: number
  onRetry?: (error: unknown, attempt: number, delayMs: number) => void
  // Injectable for tests
  sleep?: (ms: number) => Promise<void>
}

const defaultSleep = async (ms: number): Promise<void> => {
  await new Promise(resolve => setTimeout(resolve, ms))
}

export async function withRetry<T>(operation: () => Promise<T>, options: RetryOptions): Promise<T> {
  const {attempts, baseDelayMs, onRetry, sleep = defaultSleep} = options
  let lastError: unknown

  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await operation()
    } catch (error) {
      lastError = error
      if (attempt === attempts) {
        break
      }
      const delayMs = baseDelayMs * 2 ** (attempt - 1)
      onRetry?.(error, attempt, delayMs)
      await sleep(delayMs)
    }
  }

  throw lastError
}
