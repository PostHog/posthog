import { Counter } from 'prom-client'

import { RedisV2 } from '~/common/redis/redis-v2'

import { logger } from '../../../utils/logger'
import { CyclotronJobInvocationHogFlow } from '../../types'

export const BASE_REDIS_KEY =
    process.env.NODE_ENV === 'test' ? '@posthog-test/hogflow-trigger-dedup' : '@posthog/hogflow-trigger-dedup'

const cdpHogFlowTriggerDedupTotal = new Counter({
    name: 'cdp_hogflow_trigger_dedup_total',
    help: 'Outcome of trigger-layer dedup at cdp-events-consumer for hogflow invocations.',
    labelNames: ['outcome'] as const,
})

export type HogFlowTriggerDedupResult = {
    kept: CyclotronJobInvocationHogFlow[]
    dropped: CyclotronJobInvocationHogFlow[]
}

export class HogFlowTriggerDedupService {
    constructor(
        private redis: RedisV2,
        private ttlSeconds: number
    ) {}

    public async dedup(invocations: CyclotronJobInvocationHogFlow[]): Promise<HogFlowTriggerDedupResult> {
        if (!invocations.length) {
            return { kept: [], dropped: [] }
        }

        const dedupable: { invocation: CyclotronJobInvocationHogFlow; key: string }[] = []
        const passthrough: CyclotronJobInvocationHogFlow[] = []

        for (const invocation of invocations) {
            const key = this.getKey(invocation)
            if (key === null) {
                cdpHogFlowTriggerDedupTotal.labels({ outcome: 'no_key' }).inc()
                passthrough.push(invocation)
            } else {
                dedupable.push({ invocation, key })
            }
        }

        if (!dedupable.length) {
            return { kept: passthrough, dropped: [] }
        }

        const results = await this.redis.usePipeline({ name: 'hogflow-trigger-dedup', failOpen: true }, (pipeline) => {
            dedupable.forEach(({ key, invocation }) => {
                pipeline.set(key, invocation.id, 'EX', this.ttlSeconds, 'NX')
            })
        })

        if (!results) {
            // Pipeline failed entirely — fail open and keep everything we couldn't check.
            cdpHogFlowTriggerDedupTotal.labels({ outcome: 'redis_unavailable' }).inc(dedupable.length)
            return { kept: invocations, dropped: [] }
        }

        const kept: CyclotronJobInvocationHogFlow[] = [...passthrough]
        const dropped: CyclotronJobInvocationHogFlow[] = []

        dedupable.forEach(({ invocation }, index) => {
            const entry = results[index]
            if (!entry) {
                cdpHogFlowTriggerDedupTotal.labels({ outcome: 'redis_unavailable' }).inc()
                kept.push(invocation)
                return
            }
            const [err, res] = entry
            if (err) {
                cdpHogFlowTriggerDedupTotal.labels({ outcome: 'redis_error' }).inc()
                kept.push(invocation)
                return
            }
            // SET NX returns 'OK' when the key was newly written, null when it already existed.
            if (res === 'OK') {
                cdpHogFlowTriggerDedupTotal.labels({ outcome: 'kept' }).inc()
                kept.push(invocation)
            } else {
                cdpHogFlowTriggerDedupTotal.labels({ outcome: 'dropped' }).inc()
                dropped.push(invocation)
            }
        })

        return { kept, dropped }
    }

    /**
     * Release dedup keys for invocations that we were unable to queue downstream, so that the next
     * Kafka redelivery is allowed to re-attempt instead of being silently swallowed for the TTL.
     */
    public async release(invocations: CyclotronJobInvocationHogFlow[]): Promise<void> {
        const keys = invocations.map((inv) => this.getKey(inv)).filter((k): k is string => k !== null)
        if (!keys.length) {
            return
        }
        try {
            await this.redis.useClient({ name: 'hogflow-trigger-dedup-release', failOpen: true }, async (client) => {
                await client.del(...keys)
            })
        } catch (e) {
            logger.warn('🦔', '[HogFlowTriggerDedup] release failed', { err: String(e) })
        }
    }

    private getKey(invocation: CyclotronJobInvocationHogFlow): string | null {
        const workflowId = invocation.functionId
        const eventUuid = invocation.state?.event?.uuid
        // Include distinct_id so identify-replay (same event, same person UUID, but a new
        // distinct_id after `posthog.identify`) is treated as a separate trigger and not
        // suppressed. Many workflows are intentionally written to fire only once a user
        // identifies, and dedupping on (workflow_id, event_uuid) alone would silently drop
        // the post-identify invocation that those filters depend on.
        const distinctId = invocation.state?.event?.distinct_id ?? ''
        if (!workflowId || !eventUuid) {
            return null
        }
        return `${BASE_REDIS_KEY}/${workflowId}/${eventUuid}/${distinctId}`
    }
}
