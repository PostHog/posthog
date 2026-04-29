import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../_tests/redis'
import { CyclotronJobInvocationHogFlow } from '../../types'
import { BASE_REDIS_KEY, HogFlowTriggerDedupService } from './hogflow-trigger-dedup.service'

const buildInvocation = (overrides: {
    invocationId: string
    workflowId: string
    eventUuid?: string
    distinctId?: string
}): CyclotronJobInvocationHogFlow => {
    return {
        id: overrides.invocationId,
        teamId: 1,
        functionId: overrides.workflowId,
        queue: 'hogflow',
        queuePriority: 1,
        state:
            overrides.eventUuid !== undefined
                ? ({
                      event: {
                          uuid: overrides.eventUuid,
                          distinct_id: overrides.distinctId ?? 'distinct-default',
                      } as any,
                      actionStepCount: 0,
                  } as any)
                : null,
        hogFlow: { id: overrides.workflowId, team_id: 1 } as any,
        filterGlobals: {} as any,
    }
}

describe('HogFlowTriggerDedupService', () => {
    let hub: Hub
    let redis: RedisV2
    let service: HogFlowTriggerDedupService

    beforeEach(async () => {
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
        await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)
        service = new HogFlowTriggerDedupService(redis, 60)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('returns empty result for empty input', async () => {
        const result = await service.dedup([])
        expect(result).toEqual({ kept: [], dropped: [] })
    })

    it('keeps a single first-seen invocation', async () => {
        const inv = buildInvocation({ invocationId: 'inv-1', workflowId: 'wf-A', eventUuid: 'evt-1' })
        const result = await service.dedup([inv])
        expect(result.kept).toEqual([inv])
        expect(result.dropped).toEqual([])
    })

    it('drops a duplicate invocation when (workflow_id, event_uuid, distinct_id) all match', async () => {
        const first = buildInvocation({ invocationId: 'inv-1', workflowId: 'wf-A', eventUuid: 'evt-1' })
        const replay = buildInvocation({ invocationId: 'inv-2', workflowId: 'wf-A', eventUuid: 'evt-1' })

        const firstResult = await service.dedup([first])
        const replayResult = await service.dedup([replay])

        expect(firstResult.kept).toEqual([first])
        expect(replayResult.kept).toEqual([])
        expect(replayResult.dropped).toEqual([replay])
    })

    it('keeps invocations for different events on the same workflow', async () => {
        const a = buildInvocation({ invocationId: 'inv-1', workflowId: 'wf-A', eventUuid: 'evt-1' })
        const b = buildInvocation({ invocationId: 'inv-2', workflowId: 'wf-A', eventUuid: 'evt-2' })
        const result = await service.dedup([a, b])
        expect(result.kept).toEqual([a, b])
        expect(result.dropped).toEqual([])
    })

    it('keeps invocations for the same event on different workflows', async () => {
        const a = buildInvocation({ invocationId: 'inv-1', workflowId: 'wf-A', eventUuid: 'evt-1' })
        const b = buildInvocation({ invocationId: 'inv-2', workflowId: 'wf-B', eventUuid: 'evt-1' })
        const result = await service.dedup([a, b])
        expect(result.kept).toEqual([a, b])
        expect(result.dropped).toEqual([])
    })

    it('splits a mixed batch of new and duplicate invocations', async () => {
        const first = buildInvocation({ invocationId: 'inv-1', workflowId: 'wf-A', eventUuid: 'evt-1' })
        await service.dedup([first])

        const newOne = buildInvocation({ invocationId: 'inv-2', workflowId: 'wf-A', eventUuid: 'evt-2' })
        const duplicate = buildInvocation({ invocationId: 'inv-3', workflowId: 'wf-A', eventUuid: 'evt-1' })

        const result = await service.dedup([newOne, duplicate])
        expect(result.kept).toEqual([newOne])
        expect(result.dropped).toEqual([duplicate])
    })

    it('passes through invocations missing an event uuid (cannot be keyed)', async () => {
        const noEvent = buildInvocation({ invocationId: 'inv-1', workflowId: 'wf-A' })
        const result = await service.dedup([noEvent])
        expect(result.kept).toEqual([noEvent])
        expect(result.dropped).toEqual([])
    })

    it('keeps both invocations on identify-replay (same event_uuid, different distinct_id)', async () => {
        // Same person, same purchase event, but identify happened between the two emissions
        // so distinct_id changed from anonymous UUID to email. Some workflows are written to
        // fire only after identification, so we must not suppress the post-identify invocation.
        const beforeIdentify = buildInvocation({
            invocationId: 'inv-1',
            workflowId: 'wf-A',
            eventUuid: 'evt-1',
            distinctId: 'anon-uuid-aaaa',
        })
        const afterIdentify = buildInvocation({
            invocationId: 'inv-2',
            workflowId: 'wf-A',
            eventUuid: 'evt-1',
            distinctId: 'user@example.com',
        })

        const firstResult = await service.dedup([beforeIdentify])
        const secondResult = await service.dedup([afterIdentify])

        expect(firstResult.kept).toEqual([beforeIdentify])
        expect(secondResult.kept).toEqual([afterIdentify])
        expect(secondResult.dropped).toEqual([])
    })

    it('drops a true replay (same event_uuid AND same distinct_id)', async () => {
        // Kafka rebalance offset replay - identical input on both attempts.
        const first = buildInvocation({
            invocationId: 'inv-1',
            workflowId: 'wf-A',
            eventUuid: 'evt-1',
            distinctId: 'user@example.com',
        })
        const replay = buildInvocation({
            invocationId: 'inv-2',
            workflowId: 'wf-A',
            eventUuid: 'evt-1',
            distinctId: 'user@example.com',
        })

        const firstResult = await service.dedup([first])
        const replayResult = await service.dedup([replay])

        expect(firstResult.kept).toEqual([first])
        expect(replayResult.kept).toEqual([])
        expect(replayResult.dropped).toEqual([replay])
    })

    it('atomically dedups when both invocations of the same key arrive in one batch', async () => {
        // Same workflow + event in one batch — only the first should be kept.
        const first = buildInvocation({ invocationId: 'inv-1', workflowId: 'wf-A', eventUuid: 'evt-1' })
        const duplicate = buildInvocation({ invocationId: 'inv-2', workflowId: 'wf-A', eventUuid: 'evt-1' })
        const result = await service.dedup([first, duplicate])
        expect(result.kept).toEqual([first])
        expect(result.dropped).toEqual([duplicate])
    })

    it('release() clears keys so a re-attempt is allowed through', async () => {
        const first = buildInvocation({ invocationId: 'inv-1', workflowId: 'wf-A', eventUuid: 'evt-1' })
        const replay = buildInvocation({ invocationId: 'inv-2', workflowId: 'wf-A', eventUuid: 'evt-1' })

        const firstResult = await service.dedup([first])
        expect(firstResult.kept).toEqual([first])

        await service.release(firstResult.kept)

        const replayResult = await service.dedup([replay])
        expect(replayResult.kept).toEqual([replay])
        expect(replayResult.dropped).toEqual([])
    })
})
