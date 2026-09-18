import type { CustomerJourney, CustomerJourneyEndReason } from 'lib/customerJourneys/createCustomerJourney'

export interface QueryJourneyDescriptor {
    startRequest: (queryId: string) => CustomerJourney | null
    requireObservedSurface?: boolean
}

export interface QueryJourneyReceipt {
    generation: number
    queryId: string
    response: unknown
}

function safely(callback: () => void): void {
    try {
        callback()
    } catch {
        // Observation must never change query execution or rendering.
    }
}

export class QueryJourneyObserver {
    private generation = 0
    private journey: CustomerJourney | null = null
    private receipt: QueryJourneyReceipt | null = null
    private owner: symbol | null = null

    replace(): number {
        this.stop('superseded')
        return ++this.generation
    }

    start(descriptor: QueryJourneyDescriptor | undefined, queryId: string): void {
        if (descriptor && (!descriptor.requireObservedSurface || this.owner)) {
            safely(() => {
                this.journey = descriptor.startRequest(queryId)
            })
        }
    }

    observe(owner: symbol): void {
        this.owner = owner
    }

    unobserve(owner: symbol): void {
        if (this.owner === owner) {
            this.owner = null
            this.stop('observation_stopped')
        }
    }

    received(generation: number, queryId: string, response: unknown): QueryJourneyReceipt | null {
        if (this.journey && generation === this.generation) {
            return (this.receipt = { generation, queryId, response })
        }
        return null
    }

    acknowledge(generation: number, response: unknown): void {
        if (this.journey && this.receipt?.generation === generation && this.receipt.response === response) {
            const journey = this.journey
            this.journey = null
            this.receipt = null
            safely(() => journey.firstUseful())
            safely(() => journey.finish('usable'))
        }
    }

    fail(generation: number): void {
        if (this.journey && generation === this.generation) {
            const journey = this.journey
            this.journey = null
            this.receipt = null
            safely(() => journey.finish('failed', { error_type: 'query_error' }))
        }
    }

    stop(reason: CustomerJourneyEndReason): void {
        const journey = this.journey
        this.journey = null
        this.receipt = null
        if (journey) {
            safely(() => journey.dispose(reason))
        }
    }
}
