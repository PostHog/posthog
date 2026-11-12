import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { KAFKA_HOG_INVOCATION_RESULTS } from '~/common/config/kafka-topics'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import {
    createExampleInvocation,
    createHogExecutionGlobals,
    createHogFunction,
    insertHogFunction,
} from '../_tests/fixtures'
import { HogWatcherState } from '../services/monitoring/hog-watcher.service'
import { createCrashGuardValkeyPool } from '../services/poison-batch/crash-guard'
import { CyclotronJobInvocationHogFunction, HogFunctionInvocationGlobalsWithInputs, HogFunctionType } from '../types'
import { CdpCyclotronDeadLetterWorker } from './cdp-cyclotron-dead-letter-worker.consumer'

jest.setTimeout(1000)

describe('CdpCyclotronDeadLetterWorker', () => {
    let hub: Hub
    let team: Team
    let fn: HogFunctionType
    let globals: HogFunctionInvocationGlobalsWithInputs

    beforeEach(async () => {
        hub = await createHub({ HOG_INVOCATION_RESULTS_ENABLED: true })
        team = (await createTestTeamFixture(hub.postgres)).team
        fn = await insertHogFunction(
            hub.postgres,
            team.id,
            createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
                template_id: 'template-webhook',
            })
        )
        globals = { ...createHogExecutionGlobals({}), inputs: { url: 'https://posthog.com' } }
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await closeHub(hub)
    })

    // The dead letter queue reads the invocation back without its function, which is what the worker gets.
    const queued = (): CyclotronJobInvocationHogFunction => {
        const { hogFunction: _unloaded, ...rest } = createExampleInvocation(fn, globals)
        return { ...rest, queueSource: 'postgres' } as CyclotronJobInvocationHogFunction
    }

    it('disables the function once enough of its invocations are quarantined', async () => {
        const worker = new CdpCyclotronDeadLetterWorker(
            { ...hub, CDP_QUARANTINE_AUTO_DISABLE: true, CDP_QUARANTINE_DISABLE_THRESHOLD: 1 },
            {
                ...createCdpConsumerDeps(hub),
                crashGuardSettings: {
                    valkey: createCrashGuardValkeyPool(hub),
                    mode: 'shadow',
                    maxAttempts: 3,
                    keyTtlSeconds: 60,
                },
            },
            createMockJobQueue()
        )

        await expect(
            worker['quarantine'].quarantine([{ invocation: queued(), partition: 0, offset: 12 }])
        ).resolves.toBeUndefined()

        expect(mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_HOG_INVOCATION_RESULTS)).toHaveLength(1)
        expect((await worker.hogWatcher.getPersistedState(fn.id)).state).toEqual(HogWatcherState.disabled)
    })
})
