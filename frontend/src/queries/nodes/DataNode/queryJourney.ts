import type { CustomerJourney, CustomerJourneyEndReason } from 'lib/customerJourneys/createCustomerJourney'
import { customerJourneyFailure } from 'lib/customerJourneys/customerJourneyFailure'
import { CustomerJourneyScope } from 'lib/customerJourneys/CustomerJourneyScope'

export interface QueryJourneyDescriptor {
    startRequest: (queryId: string) => CustomerJourney | null
    /** Only requests started while a result surface is observed belong to this journey. */
    requireObservedSurface?: boolean
}

export interface QueryJourneyReceipt {
    generation: number
    queryId: string
    response: unknown
}

export class QueryJourneyObserver {
    private generation = 0
    private readonly scope = new CustomerJourneyScope<{
        handle: CustomerJourney
        receipt: QueryJourneyReceipt | null
    }>()
    private readonly owners = new Set<symbol>()

    replace(): number {
        this.stop('superseded')
        return ++this.generation
    }

    start(descriptor: QueryJourneyDescriptor | undefined, queryId: string): void {
        if (descriptor && (!descriptor.requireObservedSurface || this.owners.size > 0)) {
            this.scope.replace(() => {
                const handle = descriptor.startRequest(queryId)
                return handle ? { handle, receipt: null } : null
            })
        }
    }

    observe(owner: symbol): void {
        this.owners.add(owner)
    }

    unobserve(owner: symbol): void {
        if (this.owners.delete(owner) && this.owners.size === 0) {
            this.stop('observation_stopped')
        }
    }

    received(generation: number, queryId: string, response: unknown): QueryJourneyReceipt | null {
        if (this.scope.current && generation === this.generation) {
            return (this.scope.current.receipt = { generation, queryId, response })
        }
        return null
    }

    acknowledge(generation: number, response: unknown): void {
        const receipt = this.scope.current?.receipt
        if (receipt?.generation === generation && receipt.response === response) {
            this.scope.firstUseful()
            this.scope.finish('usable')
        }
    }

    fail(generation: number, error: unknown): void {
        if (generation === this.generation) {
            const { outcome, error_type } = customerJourneyFailure(error)
            this.scope.finish(outcome, { error_type })
        }
    }

    stop(reason: CustomerJourneyEndReason): void {
        this.scope.dispose(reason)
    }
}
