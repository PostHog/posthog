import { Counter } from 'prom-client'

import { PluginsServerConfig } from '../../types'
import { shadowFetchContext } from '../services/hog-executor.service'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

const shadowInvocationsProcessed = new Counter({
    name: 'cdp_shadow_invocations_processed',
    help: 'Number of invocations processed by the shadow worker',
    labelNames: ['outcome'],
})

/**
 * Shadow worker that consumes from the shadow Cyclotron database.
 * Executes the full invocation pipeline (including bytecode) but with no-op HTTP fetches,
 * scoped via AsyncLocalStorage so other workers in the same process are unaffected.
 *
 * Skips Kafka log/metric production to avoid shadow data mixing with real data.
 * Instead exposes Prometheus metrics for observability.
 */
export class CdpCyclotronShadowWorker extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronShadowWorker'

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps) {
        const shadowConfig: PluginsServerConfig = {
            ...config,
            CYCLOTRON_DATABASE_URL: config.CYCLOTRON_SHADOW_DATABASE_URL,
            CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: 'shadow',
            CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING: '*:postgres',
        }
        super(shadowConfig, deps)
    }

    public async processInvocations(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationResult[]> {
        return shadowFetchContext.run(true, () => super.processInvocations(invocations))
    }

    /**
     * Override processBatch to skip monitoring, logging, and watcher calls.
     * Only re-queues results back to the shadow DB so multi-step functions continue.
     */
    public async processBatch(
        invocations: CyclotronJobInvocation[]
    ): Promise<{ backgroundTask: Promise<any>; invocationResults: CyclotronJobInvocationResult[] }> {
        if (!invocations.length) {
            return { backgroundTask: Promise.resolve(), invocationResults: [] }
        }

        const invocationResults = await this.processInvocations(invocations)

        for (const result of invocationResults) {
            const outcome = result.error ? 'error' : result.finished ? 'completed' : 'continuing'
            shadowInvocationsProcessed.inc({ outcome })
        }

        const backgroundTask = this.queueInvocationResults(invocationResults)

        return { backgroundTask, invocationResults }
    }
}
