import { Counter } from 'prom-client'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { RedisClient, RedisV2 } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import { CyclotronJobInvocationHogFlow } from '../../types'
import { dualRead } from '../../utils/dual-store'

const DUPLICATE_OBSERVATION_TTL_SECONDS = 15 * 60

const hogflowDuplicateInvocationDetectedTotal = new Counter({
    name: 'hogflow_duplicate_invocation_detected_total',
    help: 'Fired once per action reached by a duplicate invocation of the same (workflow, event). Inflated by N actions per duplicate pair - treat as trend signal, not exact count.',
    labelNames: ['workflow_id'],
})

/**
 * Detects duplicate workflow invocations via a SET-NX key per (workflow, event, action).
 * Every observation fires against both Redis and Valkey in parallel; the store this feature
 * currently reads from is the one whose verdict drives the duplicate-detected metric.
 */
export class HogFlowDuplicateObserverService {
    constructor(
        private readonly redis: RedisV2,
        private readonly redisMirror: RedisV2
    ) {}

    public async observe(
        invocation: CyclotronJobInvocationHogFlow,
        currentAction: HogFlowAction
    ): Promise<{ duplicate: boolean }> {
        const eventUuid = invocation.state?.event?.uuid
        if (!eventUuid) {
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
            const existingId = await dualRead(
                'hog-flow-duplicate-observer.observe',
                () => this.redis.useClient({ name: 'hogflow-observe', failOpen: true }, setNxGet),
                () => this.redisMirror.useClient({ name: 'hogflow-observe-mirror', failOpen: true }, setNxGet),
                (primary, secondary) => Boolean(primary) === Boolean(secondary)
            )
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
