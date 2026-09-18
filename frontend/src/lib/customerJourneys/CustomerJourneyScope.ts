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
    public current: State | null = null

    public constructor(
        private readonly summarize: (state: State) => CustomerJourneySummary = () => ({}),
        private readonly onFinish: () => void = () => {}
    ) {}

    public replace(start: () => State | null): State | null {
        this.dispose('superseded')
        this.current = safely(start) ?? null
        return this.current
    }

    public firstUseful(): void {
        safely(() => this.current?.handle.firstUseful())
    }

    public finish(outcome: CustomerJourneyOutcome, summary: CustomerJourneySummary = {}): void {
        const current = this.current
        if (!current) {
            return
        }
        this.current = null
        const details = { ...safely(() => this.summarize(current)), ...summary }
        safely(() => current.handle.finish(outcome, details))
        safely(this.onFinish)
    }

    public dispose(reason: CustomerJourneyEndReason): void {
        this.finish(reason, { end_reason: reason })
    }
}
