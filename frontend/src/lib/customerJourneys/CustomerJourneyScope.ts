import type {
    CustomerJourney,
    CustomerJourneyEndReason,
    CustomerJourneyOutcome,
    CustomerJourneySummary,
} from './createCustomerJourney'

function safely<Result>(observe: () => Result): Result | undefined {
    try {
        return observe()
    } catch {
        // Observation must never change query execution or rendering.
        return undefined
    }
}

export class CustomerJourneyScope<State extends { handle: CustomerJourney }> {
    private active: State | null = null

    public get current(): State | null {
        return this.active
    }

    public constructor(
        private readonly summarize: (state: State) => CustomerJourneySummary = () => ({}),
        private readonly onFinish: () => void = () => {}
    ) {}

    public replace(start: () => State | null): State | null {
        this.dispose('superseded')
        this.active = safely(start) ?? null
        return this.active
    }

    public transition(expected: State, next: State): boolean {
        if (this.active !== expected || next.handle !== expected.handle) {
            return false
        }
        this.active = next
        return true
    }

    public firstUseful(): void {
        safely(() => this.current?.handle.firstUseful())
    }

    public finish(outcome: CustomerJourneyOutcome, summary: CustomerJourneySummary = {}): void {
        const current = this.current
        if (!current) {
            return
        }
        this.active = null
        const details = { ...safely(() => this.summarize(current)), ...summary }
        safely(() => current.handle.finish(outcome, details))
        safely(this.onFinish)
    }

    public dispose(reason: CustomerJourneyEndReason): void {
        this.finish(reason, { end_reason: reason })
    }
}
