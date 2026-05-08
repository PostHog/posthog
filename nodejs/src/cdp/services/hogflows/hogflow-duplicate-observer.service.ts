import { Counter } from 'prom-client'

import { RedisClient, RedisV2 } from '~/common/redis/redis-v2'

import { HogFlowAction } from '../../../schema/hogflow'
import { logger } from '../../../utils/logger'
import { CyclotronJobInvocationHogFlow } from '../../types'
import { mirrorCall } from '../../utils/mirror-call'

const DUPLICATE_OBSERVATION_TTL_SECONDS = 15 * 60

const hogflowDuplicateInvocationDetectedTotal = new Counter({
    name: 'hogflow_duplicate_invocation_detected_total',
    help: 'Fired once per action reached by a duplicate invocation of the same (workflow, event). Inflated by N actions per duplicate pair - treat as trend signal, not exact count.',
    labelNames: ['workflow_id'],
})

/**
 * Detects duplicate workflow invocations via a Redis SET-NX key per
 * (workflow, event, action). When `redisMirror` is set, every observation also
 * fires against the mirror in parallel — load is realised on the mirror; only
 * the primary drives the duplicate-detected metric.
 */
export class HogFlowDuplicateObserverService {
    constructor(
        private readonly redis: RedisV2 | null,
        private readonly redisMirror: RedisV2 | null = null
    ) {}

    public async observe(
        invocation: CyclotronJobInvocationHogFlow,
        currentAction: HogFlowAction
    ): Promise<{ duplicate: boolean }> {
        const eventUuid = invocation.state?.event?.uuid
        if (!this.redis || !eventUuid) {
            return { duplicate: false }
        }
        const key = `hogflow:observe:${invocation.functionId}:${eventUuid}:${currentAction.id}`

        // SET ... NX GET (Redis 7+ / Valkey 7.2+) sets the key when absent and returns the
        // existing value when present — one round-trip instead of GET-then-SETNX. ioredis 4.x
        // types only describe 'OK' | null for the return, so we cast to the actual GET payload.
        const setNxGet = (client: RedisClient): Promise<string | null> =>
            client.set(key, invocation.id, ['EX', String(DUPLICATE_OBSERVATION_TTL_SECONDS), 'NX', 'GET']) as Promise<
                string | null
            >

        let duplicate = false
        try {
            const [existingId] = await Promise.all([
                this.redis.useClient({ name: 'hogflow-observe', failOpen: true }, setNxGet),
                mirrorCall('hog-flow-duplicate-observer.observe', () =>
                    this.redisMirror?.useClient({ name: 'hogflow-observe-mirror', failOpen: true }, setNxGet)
                ),
            ])
            if (existingId && existingId !== invocation.id) {
                duplicate = true
                hogflowDuplicateInvocationDetectedTotal.inc({ workflow_id: invocation.functionId })
            }
        } catch (error) {
            logger.debug('🦔', '[HogFlowDuplicateObserver] failed', { error: String(error) })
        }
        return { duplicate }
    }
}
