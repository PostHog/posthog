/**
 * A fed batch's soft deadline. Past it the framework stops starting steps, but
 * it never interrupts a running one: the consumer's ack watchdog is the hard
 * limit.
 */
export class BatchBudget {
    private static readonly UNLIMITED = new BatchBudget(Infinity)

    private expired = false

    private constructor(
        /** Epoch milliseconds, or `Infinity` for no deadline. */
        readonly softAt: number
    ) {}

    static softDeadline(softAt: number): BatchBudget {
        return new BatchBudget(softAt)
    }

    static unlimited(): BatchBudget {
        return BatchBudget.UNLIMITED
    }

    // Reads the clock rather than a timer flag: synchronous steps can hold the
    // event loop past the deadline, and a timer flag would then let a late
    // element through the timeout barrier. The flag stays set, so a wall-clock
    // step backwards cannot restart a cut-off group.
    get exhausted(): boolean {
        if (!this.expired && this.softAt !== Infinity) {
            this.expired = Date.now() >= this.softAt
        }
        return this.expired
    }
}

// The server arms its admission park timer with the allowance. Node fires a
// longer timer after 1 ms, so a longer allowance would expire at once.
const MAX_TIMER_DELAY_MS = 2 ** 31 - 1

// Allowances arrive as durations, so the sender's clock never enters the arithmetic.
export function budgetDeadline(armedAt: number, budgetMs: number): number | null {
    return budgetMs === 0 || budgetMs > MAX_TIMER_DELAY_MS ? null : armedAt + budgetMs
}
