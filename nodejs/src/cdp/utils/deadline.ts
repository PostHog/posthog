const expiresAt = new WeakMap<AbortSignal, number>()

export function deadlineAfter(ms: number): AbortSignal {
    const signal = AbortSignal.timeout(ms)
    expiresAt.set(signal, performance.now() + ms)
    return signal
}

export function deadlineError(signal: AbortSignal | undefined): unknown {
    if (!signal) {
        return undefined
    }
    if (signal.aborted) {
        return signal.reason
    }
    const at = expiresAt.get(signal)
    return at !== undefined && performance.now() >= at
        ? new DOMException('The operation was aborted due to timeout', 'TimeoutError')
        : undefined
}

export function deadlineRemainingMs(signal: AbortSignal | undefined): number | undefined {
    const at = signal && expiresAt.get(signal)
    return at === undefined ? undefined : Math.max(0, at - performance.now())
}

export function throwIfDeadlinePassed(signal: AbortSignal | undefined): void {
    const error = deadlineError(signal)
    if (error !== undefined) {
        throw error
    }
}
