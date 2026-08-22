import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { delay } from '~/common/utils/utils'

import { ConfigurationRequestScheduler } from './configuration-policy'
import { BudgetBlockReason, HostBudget } from './host-budget'

export type ScheduledRequest<T> =
    | { ran: true; value: T }
    | { ran: false; reason: BudgetBlockReason | 'connection_limit'; waitMs: number }

export class OriginRequestScheduler implements ConfigurationRequestScheduler {
    private readonly inFlight: ConcurrencyController

    constructor(
        private readonly budget: HostBudget,
        maxInFlightRequests: number
    ) {
        this.inFlight = new ConcurrencyController(maxInFlightRequests)
    }

    public run<T>(url: URL, deadlineMs: number, request: () => Promise<T>): Promise<ScheduledRequest<T>> {
        return this.runScheduled(url.origin, deadlineMs, true, request)
    }

    public runImage<T>(origin: string, deadlineMs: number, request: () => Promise<T>): Promise<ScheduledRequest<T>> {
        return this.runScheduled(origin, deadlineMs, false, request)
    }

    public get running(): number {
        return this.inFlight.running
    }

    private async runScheduled<T>(
        origin: string,
        deadlineMs: number,
        configurationRequest: boolean,
        request: () => Promise<T>
    ): Promise<ScheduledRequest<T>> {
        const nowMs = Date.now()
        if (configurationRequest && !this.budget.configurationRequestStarted(origin, nowMs)) {
            return { ran: false, reason: 'origin_map_full', waitMs: 0 }
        }
        try {
            const grant = this.budget.take(origin, nowMs, deadlineMs, configurationRequest)
            if (!grant.granted) {
                return { ran: false, reason: grant.reason, waitMs: grant.waitMs }
            }
            if (grant.waitMs > 0) {
                await delay(grant.waitMs)
            }
            if (Date.now() > deadlineMs) {
                this.budget.returnGrant(origin, Date.now(), grant.reservedStartAtMs)
                return { ran: false, reason: 'deadline', waitMs: 0 }
            }
            for (;;) {
                const scheduled = await this.inFlight.run({
                    debugTag: origin,
                    fn: async () => {
                        const queuedUntilMs = Date.now()
                        const blocked = configurationRequest
                            ? null
                            : this.budget.blockedReason(origin, queuedUntilMs, grant.halfOpenProbe)
                        if (queuedUntilMs > deadlineMs || blocked) {
                            return { kind: 'stopped', reason: blocked ?? ('deadline' as const) } as const
                        }
                        const startWaitMs = configurationRequest
                            ? 0
                            : this.budget.requestStartWaitMs(origin, queuedUntilMs)
                        if (startWaitMs > 0) {
                            return { kind: 'wait', waitMs: startWaitMs } as const
                        }
                        if (!this.budget.acquireConnection(origin, queuedUntilMs)) {
                            return { kind: 'stopped', reason: 'connection_limit' as const } as const
                        }
                        try {
                            this.budget.markRequestStarted(origin, Date.now(), grant.reservedStartAtMs)
                            return { kind: 'ran', value: await request() } as const
                        } finally {
                            this.budget.releaseConnection(origin)
                        }
                    },
                })
                if (scheduled.kind === 'ran') {
                    return { ran: true, value: scheduled.value }
                }
                if (scheduled.kind === 'stopped') {
                    this.budget.returnGrant(origin, Date.now(), grant.reservedStartAtMs)
                    return {
                        ran: false,
                        reason: scheduled.reason,
                        waitMs: this.budget.blockedForMs(origin, Date.now()),
                    }
                }
                if (Date.now() + scheduled.waitMs > deadlineMs) {
                    this.budget.returnGrant(origin, Date.now(), grant.reservedStartAtMs)
                    return { ran: false, reason: 'deadline', waitMs: scheduled.waitMs }
                }
                await delay(scheduled.waitMs)
            }
        } finally {
            if (configurationRequest) {
                this.budget.configurationRequestFinished(origin)
            }
        }
    }
}
