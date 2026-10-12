/**
 * A fed batch's soft deadline. Past it the framework stops starting steps, but
 * it never interrupts a running one: the consumer's ack watchdog is the hard
 * limit. A timer sets the flag because checkpoints read `exhausted` once per
 * element per step.
 */
export class BatchBudget {
    private static readonly UNLIMITED = new BatchBudget(Infinity)

    private expired = false
    private timer: ReturnType<typeof setTimeout> | null = null

    private constructor(
        /** Epoch milliseconds, or `Infinity` for no deadline. */
        readonly softAt: number
    ) {
        if (softAt === Infinity) {
            return
        }
        const remainingMs = softAt - Date.now()
        if (remainingMs <= 0) {
            // A zero-delay timer fires after the first checkpoint can run.
            this.expired = true
            return
        }
        this.timer = setTimeout(() => {
            this.expired = true
        }, remainingMs)
        this.timer.unref?.()
    }

    static softDeadline(softAt: number): BatchBudget {
        return new BatchBudget(softAt)
    }

    static unlimited(): BatchBudget {
        return BatchBudget.UNLIMITED
    }

    get exhausted(): boolean {
        return this.expired
    }

    settle(): void {
        if (this.timer) {
            clearTimeout(this.timer)
            this.timer = null
        }
    }
}

// Node fires a longer timer after 1 ms, so a longer allowance would expire at once.
const MAX_TIMER_DELAY_MS = 2 ** 31 - 1

// Allowances arrive as durations, so the sender's clock never enters the arithmetic.
export function budgetDeadline(armedAt: number, budgetMs: number): number | null {
    return budgetMs === 0 || budgetMs > MAX_TIMER_DELAY_MS ? null : armedAt + budgetMs
}
