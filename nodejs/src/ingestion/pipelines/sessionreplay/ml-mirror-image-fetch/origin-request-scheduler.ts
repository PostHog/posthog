import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { delay } from '~/common/utils/utils'

import type { ImageFetchBlockReason } from './block-reason'
import { ConfigurationRequestScheduler } from './configuration-policy'
import { BudgetBlockReason, BudgetGrant, HostBudget } from './host-budget'
import { ImageFetchRequestMetrics, SchedulerWaitScope } from './metrics'
import { politenessKey } from './politeness-key'
import { ImageFetchTopHogMetrics } from './tophog-metrics'

export type ScheduledRequest<T> =
    | { ran: true; value: T }
    | {
          ran: false
          reason: BudgetBlockReason | 'connection_limit'
          blockingReason: ImageFetchBlockReason
          waitMs: number
      }

function blockingReasonForStoppedGrant(grant: Extract<BudgetGrant, { granted: false }>): ImageFetchBlockReason {
    if (grant.reason === 'backoff') {
        return grant.backoffReason ?? 'unknown_backoff'
    }
    if (grant.reason === 'deadline') {
        return grant.waitScope ?? 'request_deadline'
    }
    return grant.reason
}

export class OriginRequestScheduler implements ConfigurationRequestScheduler {
    private readonly inFlight: ConcurrencyController

    constructor(
        private readonly budget: HostBudget,
        maxInFlightRequests: number,
        private readonly topHogMetrics?: ImageFetchTopHogMetrics
    ) {
        this.inFlight = new ConcurrencyController(maxInFlightRequests)
    }

    public run<T>(url: URL, deadlineMs: number, request: () => Promise<T>): Promise<ScheduledRequest<T>> {
        return this.runScheduled(url, deadlineMs, true, undefined, request)
    }

    public runImage<T>(
        url: URL,
        deadlineMs: number,
        request: () => Promise<T>,
        sourcePartitions?: readonly number[]
    ): Promise<ScheduledRequest<T>> {
        return this.runScheduled(url, deadlineMs, false, sourcePartitions, request)
    }

    public get running(): number {
        return this.inFlight.running
    }

    private async runScheduled<T>(
        url: URL,
        deadlineMs: number,
        configurationRequest: boolean,
        sourcePartitions: readonly number[] | undefined,
        request: () => Promise<T>
    ): Promise<ScheduledRequest<T>> {
        const origin = url.origin
        const registrableDomain = politenessKey(url.hostname)
        const nowMs = Date.now()
        if (!this.budget.requestScheduled(origin, nowMs)) {
            return { ran: false, reason: 'origin_map_full', blockingReason: 'origin_map_full', waitMs: 0 }
        }
        try {
            for (;;) {
                const capacityWaitStartedAtMs = Date.now()
                const scheduled = await this.inFlight.run({
                    debugTag: registrableDomain,
                    fn: async () => {
                        const checkedAtMs = Date.now()
                        this.recordSchedulerWait(
                            'request_capacity',
                            Math.max(0, checkedAtMs - capacityWaitStartedAtMs),
                            registrableDomain,
                            configurationRequest,
                            sourcePartitions
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
                                blockingReason: blockingReasonForStoppedGrant(grant),
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
                            return {
                                kind: 'stopped',
                                reason: 'connection_limit' as const,
                                blockingReason: 'connection_limit' as const,
                                waitMs: 0,
                            } as const
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
                        blockingReason: scheduled.blockingReason,
                        waitMs: scheduled.waitMs,
                    }
                }
                if (Date.now() + scheduled.waitMs > deadlineMs) {
                    return {
                        ran: false,
                        reason: 'deadline',
                        blockingReason: scheduled.waitScope,
                        waitMs: scheduled.waitMs,
                    }
                }
                this.recordSchedulerWait(
                    scheduled.waitScope,
                    scheduled.waitMs,
                    registrableDomain,
                    configurationRequest,
                    sourcePartitions
                )
                await delay(scheduled.waitMs)
            }
        } finally {
            this.budget.requestFinished(origin)
        }
    }

    private recordSchedulerWait(
        scope: SchedulerWaitScope,
        waitMs: number,
        registrableDomain: string,
        configurationRequest: boolean,
        sourcePartitions: readonly number[] | undefined
    ): void {
        ImageFetchRequestMetrics.observeSchedulerWait(scope, waitMs / 1000, sourcePartitions)
        if (!configurationRequest) {
            this.topHogMetrics?.recordSchedulerWait(registrableDomain, sourcePartitions, scope, waitMs)
        }
    }
}
