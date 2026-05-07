import { Counter } from 'prom-client'

import { RedisV2 } from '~/common/redis/redis-v2'

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

    public async observe(invocation: CyclotronJobInvocationHogFlow, currentAction: HogFlowAction): Promise<void> {
        const eventUuid = invocation.state?.event?.uuid
        if (!this.redis || !eventUuid) {
            return
        }
        const key = `hogflow:observe:${invocation.functionId}:${eventUuid}:${currentAction.id}`

        try {
            await Promise.all([
                this.redis.useClient({ name: 'hogflow-observe', failOpen: true }, async (client) => {
                    const wasSet = await client.set(key, invocation.id, 'EX', DUPLICATE_OBSERVATION_TTL_SECONDS, 'NX')
                    if (wasSet) {
                        return
                    }
                    const existingId = await client.get(key)
                    if (existingId && existingId !== invocation.id) {
                        hogflowDuplicateInvocationDetectedTotal.inc({ workflow_id: invocation.functionId })
                    }
                }),
                mirrorCall('hog-flow-duplicate-observer.observe', () =>
                    this.redisMirror?.useClient({ name: 'hogflow-observe-mirror', failOpen: true }, async (client) => {
                        const wasSet = await client.set(
                            key,
                            invocation.id,
                            'EX',
                            DUPLICATE_OBSERVATION_TTL_SECONDS,
                            'NX'
                        )
                        if (!wasSet) {
                            await client.get(key)
                        }
                    })
                ),
            ])
        } catch (error) {
            logger.debug('🦔', '[HogFlowDuplicateObserver] failed', { error: String(error) })
        }
    }
}
