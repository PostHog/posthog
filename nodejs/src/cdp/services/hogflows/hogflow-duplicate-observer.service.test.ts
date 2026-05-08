import { register } from 'prom-client'

import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../_tests/redis'
import { CyclotronJobInvocationHogFlow } from '../../types'
import { HogFlowDuplicateObserverService } from './hogflow-duplicate-observer.service'

const KEY_PREFIX = 'hogflow:observe:'

const buildInvocation = (overrides: { id?: string; functionId?: string; eventUuid?: string | null } = {}) =>
    ({
        id: overrides.id ?? 'invocation-1',
        functionId: overrides.functionId ?? 'workflow-1',
        state: { event: overrides.eventUuid === null ? undefined : { uuid: overrides.eventUuid ?? 'event-1' } },
    }) as unknown as CyclotronJobInvocationHogFlow

const buildAction = (id: string) => ({ id, type: 'function' }) as any

const dupCounterValue = async (workflowId: string): Promise<number> => {
    const metric = register.getSingleMetric('hogflow_duplicate_invocation_detected_total') as any
    const data = await metric.get()
    const found = data.values.find((v: any) => v.labels.workflow_id === workflowId)
    return found?.value ?? 0
}

describe('HogFlowDuplicateObserverService', () => {
    jest.retryTimes(3)

    let hub: Hub
    let redis: RedisV2

    beforeAll(async () => {
        hub = await createHub()
        redis = createRedisV2PoolFromConfig({
            connection: hub.CDP_REDIS_HOST
                ? {
                      url: hub.CDP_REDIS_HOST,
                      options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                  }
                : { url: hub.REDIS_URL },
            poolMinSize: hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
        })
    })

    afterAll(async () => {
        await closeHub(hub)
    })

    beforeEach(async () => {
        await deleteKeysWithPrefix(redis, KEY_PREFIX)
        register.resetMetrics()
    })

    const readKey = async (key: string): Promise<string | null> =>
        (await redis.useClient({ name: 'read' }, (client) => client.get(key))) ?? null

    it('is a no-op when redis is null', async () => {
        const observer = new HogFlowDuplicateObserverService(null)
        await observer.observe(buildInvocation(), buildAction('action-1'))
        // Nothing to assert beyond not throwing — verifies the early return.
    })

    it('is a no-op when invocation has no eventUuid', async () => {
        const observer = new HogFlowDuplicateObserverService(redis)
        await observer.observe(buildInvocation({ eventUuid: null }), buildAction('action-1'))
        const keys = await redis.useClient({ name: 'keys' }, (client) => client.keys(`${KEY_PREFIX}*`))
        expect(keys ?? []).toHaveLength(0)
    })

    it('writes the key on first observation and does not flag a duplicate', async () => {
        const observer = new HogFlowDuplicateObserverService(redis)
        await observer.observe(buildInvocation({ id: 'inv-A' }), buildAction('action-1'))

        const stored = await readKey('hogflow:observe:workflow-1:event-1:action-1')
        expect(stored).toBe('inv-A')
        expect(await dupCounterValue('workflow-1')).toBe(0)
    })

    it('does not flag a duplicate when the same invocation re-observes', async () => {
        const observer = new HogFlowDuplicateObserverService(redis)
        const inv = buildInvocation({ id: 'inv-A' })
        await observer.observe(inv, buildAction('action-1'))
        await observer.observe(inv, buildAction('action-1'))

        expect(await dupCounterValue('workflow-1')).toBe(0)
    })

    it('flags a duplicate when a different invocation hits the same key', async () => {
        const observer = new HogFlowDuplicateObserverService(redis)
        await observer.observe(buildInvocation({ id: 'inv-A' }), buildAction('action-1'))
        await observer.observe(buildInvocation({ id: 'inv-B' }), buildAction('action-1'))

        // The second observation must NOT overwrite the first (NX) — verifies single-call atomicity.
        expect(await readKey('hogflow:observe:workflow-1:event-1:action-1')).toBe('inv-A')
        expect(await dupCounterValue('workflow-1')).toBe(1)
    })

    it('writes to the mirror in parallel with the primary', async () => {
        const mirror = {
            useClient: jest.fn().mockResolvedValue('OK'),
        } as unknown as RedisV2

        const observer = new HogFlowDuplicateObserverService(redis, mirror)
        await observer.observe(buildInvocation({ id: 'inv-A' }), buildAction('action-1'))

        expect(mirror.useClient).toHaveBeenCalledTimes(1)
        expect((mirror.useClient as jest.Mock).mock.calls[0][0]).toMatchObject({
            name: 'hogflow-observe-mirror',
            failOpen: true,
        })
    })

    it('does not break the primary when the mirror throws', async () => {
        const mirror = {
            useClient: jest.fn().mockRejectedValue(new Error('mirror exploded')),
        } as unknown as RedisV2

        const observer = new HogFlowDuplicateObserverService(redis, mirror)
        await observer.observe(buildInvocation({ id: 'inv-A' }), buildAction('action-1'))

        expect(await readKey('hogflow:observe:workflow-1:event-1:action-1')).toBe('inv-A')
    })
})
