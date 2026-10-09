/**
 * The time allowance one fed batch has, shared by every element of that batch.
 * It carries one soft deadline, absolute epoch milliseconds, and it is the one
 * the framework checkpoints read: when it passes the framework stops starting
 * work, elements the budget cut off complete as `TIMEOUT`, and in-flight steps
 * are allowed to finish. Nothing here bounds a step that never returns — the
 * consumer's ack watchdog is the hard limit.
 *
 * A budget enforces by existing: one with a deadline cuts work off at it.
 * `unlimited()` is the neutral element, so there is no "no budget" state to
 * branch on: it never exhausts, which makes every checkpoint a no-op.
 *
 * Expiry is a flag a timer sets rather than a clock comparison, because
 * `exhausted` is read once per element per step.
 */
export class BatchBudget {
    private static readonly UNLIMITED = new BatchBudget(Infinity)

    private expired = false
    private timer: ReturnType<typeof setTimeout> | null = null

    private constructor(
        /** Absolute epoch milliseconds, or `Infinity` when there is no soft deadline. */
        readonly softAt: number
    ) {
        if (softAt === Infinity) {
            return
        }
        const remainingMs = softAt - Date.now()
        if (remainingMs <= 0) {
            // Already spent, typically on the admission wait. A zero-delay timer
            // would only fire on a later tick, and the first checkpoint can run
            // before that, so settle the flag here instead.
            this.expired = true
            return
        }
        this.timer = setTimeout(() => {
            this.expired = true
        }, remainingMs)
        // A budget outlives its batch only until the deadline it was armed for,
        // so the timer must not hold the process open in the meantime.
        this.timer.unref?.()
    }

    static softDeadline(softAt: number): BatchBudget {
        return new BatchBudget(softAt)
    }

    /** One shared instance: it holds no per-batch state and never changes. */
    static unlimited(): BatchBudget {
        return BatchBudget.UNLIMITED
    }

    get exhausted(): boolean {
        return this.expired
    }

    /** Drop the pending deadline once its batch is done needing one. */
    settle(): void {
        if (this.timer) {
            clearTimeout(this.timer)
            this.timer = null
        }
    }
}

/**
 * The absolute deadline of a relative allowance armed at `armedAt`, or `null`
 * when the allowance is `0`, which means no deadline. Allowances arrive as
 * durations rather than instants so that a sender's clock never enters the
 * arithmetic; arming them at one point makes every wait since then count.
 */
export function budgetDeadline(armedAt: number, budgetMs: number): number | null {
    return budgetMs === 0 ? null : armedAt + budgetMs
}
