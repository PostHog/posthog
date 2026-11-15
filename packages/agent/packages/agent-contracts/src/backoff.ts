export interface BackoffOptions {
  initialDelayMs: number;
  maxDelayMs?: number;
  multiplier?: number;
}

/**
 * Calculate delay for exponential backoff
 * @param attempt - Zero-indexed attempt number (0 = first retry)
 * @param options - Backoff configuration
 * @returns Delay in milliseconds
 */
export function getBackoffDelay(
  attempt: number,
  options: BackoffOptions,
): number {
  const { initialDelayMs, maxDelayMs, multiplier = 2 } = options;
  const delay = initialDelayMs * multiplier ** attempt;
  return maxDelayMs ? Math.min(delay, maxDelayMs) : delay;
}

/**
 * Sleep with exponential backoff delay.
 *
 * Pass an AbortSignal to make the sleep cancelable: on abort the timer is
 * cleared and the promise resolves immediately (it never rejects), so a
 * retry loop can bail out on its own `signal.aborted` check.
 */
export function sleepWithBackoff(
  attempt: number,
  options: BackoffOptions,
  signal?: AbortSignal,
): Promise<void> {
  const delay = getBackoffDelay(attempt, options);
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve();
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      resolve();
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, delay);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
