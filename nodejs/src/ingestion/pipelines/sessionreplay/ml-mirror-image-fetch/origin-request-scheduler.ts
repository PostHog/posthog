import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { delay } from '~/common/utils/utils'

import { ConfigurationRequestScheduler } from './configuration-policy'
import { BudgetBlockReason, HostBudget } from './host-budget'
import { ImageFetchRequestMetrics } from './metrics'
import { politenessKey } from './politeness-key'

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
        return this.runScheduled(url, deadlineMs, true, request)
    }

    public runImage<T>(url: URL, deadlineMs: number, request: () => Promise<T>): Promise<ScheduledRequest<T>> {
        return this.runScheduled(url, deadlineMs, false, request)
    }

    public get running(): number {
        return this.inFlight.running
    }

    private async runScheduled<T>(
        url: URL,
        deadlineMs: number,
        configurationRequest: boolean,
        request: () => Promise<T>
    ): Promise<ScheduledRequest<T>> {
        const origin = url.origin
        const registrableDomain = politenessKey(url.hostname)
        const nowMs = Date.now()
        if (!this.budget.requestScheduled(origin, nowMs)) {
            return { ran: false, reason: 'origin_map_full', waitMs: 0 }
        }
        try {
            for (;;) {
                const capacityWaitStartedAtMs = Date.now()
                const scheduled = await this.inFlight.run({
                    debugTag: registrableDomain,
                    fn: async () => {
                        const checkedAtMs = Date.now()
                        ImageFetchRequestMetrics.observeSchedulerWait(
                            'request_capacity',
                            Math.max(0, checkedAtMs - capacityWaitStartedAtMs) / 1000
                        )
                        const grant = this.budget.take(
                            registrableDomain,
                            origin,
                            checkedAtMs,
                            deadlineMs,
                            configurationRequest
                        )
                        if (!grant.granted) {
                            return {
                                kind: 'stopped',
                                reason: grant.reason,
                                waitMs: grant.waitMs,
                            } as const
                        }
                        if (grant.waitMs > 0) {
                            return {
                                kind: 'wait',
                                waitMs: grant.waitMs,
                                waitScope: grant.waitScope ?? 'registrable_domain_rate',
                            } as const
                        }
                        if (!this.budget.acquireConnection(registrableDomain, origin)) {
                            this.budget.returnGrant(
                                registrableDomain,
                                origin,
                                checkedAtMs,
                                grant.reservedStartAtMs,
                                grant.halfOpenProbe
                            )
                            return { kind: 'stopped', reason: 'connection_limit' as const, waitMs: 0 } as const
                        }
                        try {
                            this.budget.markRequestStarted(
                                registrableDomain,
                                origin,
                                Date.now(),
                                grant.reservedStartAtMs,
                                configurationRequest ? 'configuration' : 'image'
                            )
                            return { kind: 'ran', value: await request() } as const
                        } finally {
                            this.budget.releaseConnection(registrableDomain, origin)
                        }
                    },
                })
                if (scheduled.kind === 'ran') {
                    return { ran: true, value: scheduled.value }
                }
                if (scheduled.kind === 'stopped') {
                    return {
                        ran: false,
                        reason: scheduled.reason,
                        waitMs: scheduled.waitMs,
                    }
                }
                if (Date.now() + scheduled.waitMs > deadlineMs) {
                    return { ran: false, reason: 'deadline', waitMs: scheduled.waitMs }
                }
                ImageFetchRequestMetrics.observeSchedulerWait(scheduled.waitScope, scheduled.waitMs / 1000)
                await delay(scheduled.waitMs)
            }
        } finally {
            this.budget.requestFinished(origin)
        }
    }
}
