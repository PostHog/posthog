import { z } from 'zod'

const UNIT_MS = { ms: 1, s: 1000, m: 60_000 } as const

export const Duration = z
    .string()
    .regex(/^\d+(ms|s|m)$/, { message: 'a duration such as 500ms, 30s or 5m', abort: true })

export const KILLED_EXIT_WITHIN_MS = 10_000
export const MAX_TIMER_MS = 2 ** 31 - 1
export const MAX_TERMINATION_GRACE_MS = 5 * 60_000

export const TerminationGrace = Duration.refine(
    (grace) => durationMs(grace) <= MAX_TERMINATION_GRACE_MS,
    `at most ${MAX_TERMINATION_GRACE_MS / 60_000}m, so a stopped run releases the role within its release window`
)

export const pause = (ms: number, signal: AbortSignal): Promise<void> =>
    new Promise((resolve) => {
        if (signal.aborted) {
            resolve()
            return
        }
        const done = (): void => {
            clearTimeout(timer)
            signal.removeEventListener('abort', done)
            resolve()
        }
        const timer = setTimeout(done, ms)
        signal.addEventListener('abort', done, { once: true })
    })

export function durationMs(duration: string): number {
    const [, amount, unit] = /^(\d+)(ms|s|m)$/.exec(Duration.parse(duration))!
    return Number(amount) * UNIT_MS[unit as keyof typeof UNIT_MS]
}
