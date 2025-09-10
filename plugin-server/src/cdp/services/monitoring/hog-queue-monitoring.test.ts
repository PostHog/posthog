import '~/tests/helpers/mocks/date.mock'

import { DateTime } from 'luxon'

import { deleteKeysWithPrefix } from '~/cdp/_tests/redis'
import { CdpRedis, createCdpRedisPool } from '~/cdp/redis'
import { CyclotronJobInvocation } from '~/cdp/types'
import { defaultConfig } from '~/config/config'
import { PluginsServerConfig } from '~/types'

import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../../_tests/examples'
import { createHogExecutionGlobals, createHogFunction } from '../../_tests/fixtures'
import { createInvocation } from '../../utils/invocation-utils'
import { JOB_SCHEDULED_AT_FUTURE_THRESHOLD_MS } from '../job-queue/job-queue'
import { BASE_REDIS_KEY, HogQueueMonitoring } from '../monitoring/hog-queue-monitoring'

describe('HogQueueMonitoring', () => {
    let config: PluginsServerConfig
    let redis: CdpRedis

    const exampleHogFunction = createHogFunction({
        name: 'Test hog function',
        ...HOG_EXAMPLES.simple_fetch,
        ...HOG_INPUTS_EXAMPLES.simple_fetch,
        ...HOG_FILTERS_EXAMPLES.no_filters,
    })

    const exampleHogFunction2 = createHogFunction({
        name: 'Test hog function 2',
        ...HOG_EXAMPLES.simple_fetch,
        ...HOG_INPUTS_EXAMPLES.simple_fetch,
        ...HOG_FILTERS_EXAMPLES.no_filters,
    })

    beforeEach(async () => {
        config = { ...defaultConfig }
        redis = createCdpRedisPool(config)
        await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)
    })

    describe('monitoring', () => {
        let invocations: CyclotronJobInvocation[]
        let monitor: HogQueueMonitoring

        beforeEach(() => {
            invocations = [
                {
                    ...createInvocation({ ...createHogExecutionGlobals(), inputs: {} }, exampleHogFunction),
                    queueScheduledAt: DateTime.now().plus({
                        milliseconds: JOB_SCHEDULED_AT_FUTURE_THRESHOLD_MS + 10000,
                    }),
                },
                {
                    ...createInvocation({ ...createHogExecutionGlobals(), inputs: {} }, exampleHogFunction2),
                },

                {
                    ...createInvocation({ ...createHogExecutionGlobals(), inputs: {} }, exampleHogFunction2),
                },
            ]
            config.CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE = 'kafka'
            config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING = '*:kafka'
            monitor = new HogQueueMonitoring(redis)
        })

        it('should observe invocations to redis when queued', async () => {
            await monitor.markScheduledInvocations(invocations)
            const now = DateTime.now().toMillis()

            expect(await monitor.getFunctionInvocations(exampleHogFunction.id, now)).toEqual({
                [invocations[0].id]: now + JOB_SCHEDULED_AT_FUTURE_THRESHOLD_MS + 10000,
            })
            expect(await monitor.getFunctionInvocations(exampleHogFunction2.id, now)).toEqual({
                [invocations[1].id]: now,
                [invocations[2].id]: now,
            })
        })
    })
})
