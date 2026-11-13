import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { register } from 'prom-client'

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
import {
    CdpCyclotronDeadLetterWorker,
    SKIPPED_FUNCTION_DISABLED_ERROR_KIND,
} from './cdp-cyclotron-dead-letter-worker.consumer'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

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

    it.each([
        ['skips a disabled function on the dead letter worker', true, HogWatcherState.disabled, false, true],
        [
            'skips a forcefully disabled function on the dead letter worker',
            true,
            HogWatcherState.forcefully_disabled,
            false,
            true,
        ],
        ['runs a disabled function on the hog worker', false, HogWatcherState.disabled, false, false],
        [
            'runs the invocation when the dead letter worker cannot read the function state',
            true,
            HogWatcherState.disabled,
            true,
            false,
        ],
    ] as const)('%s', async (_, deadLetter, state, watcherDown, skipped) => {
        const deps = createCdpConsumerDeps(hub)
        const worker = deadLetter
            ? new CdpCyclotronDeadLetterWorker(hub, deps, createMockJobQueue())
            : new CdpCyclotronWorker(hub, deps, createMockJobQueue(), 'hog')
        await worker.hogWatcher.forceStateChange(fn, state)
        await worker.hogWatcherMirror.forceStateChange(fn, state)
        if (watcherDown) {
            for (const watcher of [worker.hogWatcher, worker.hogWatcherMirror]) {
                jest.spyOn(watcher, 'getEffectiveStates').mockRejectedValue(new Error('redis down'))
            }
        }
        const invocation = queued()

        const results = await worker.processInvocations([invocation])

        const skippedRows = mockProducerObserver
            .getProducedKafkaMessagesForTopic(KAFKA_HOG_INVOCATION_RESULTS)
            .map((x) => x.value)
            .filter((row) => row.error_kind === SKIPPED_FUNCTION_DISABLED_ERROR_KIND)
        if (skipped) {
            expect(results).toEqual([])
            expect(mockFetch).not.toHaveBeenCalled()
            expect(skippedRows).toEqual([
                expect.objectContaining({
                    invocation_id: invocation.id,
                    function_id: fn.id,
                    team_id: team.id,
                    status: 'failed',
                }),
            ])
        } else {
            expect(results).toEqual([expect.objectContaining({ finished: true })])
            expect(skippedRows).toEqual([])
        }
    })

    it('reports the function on the gauge once enough of its invocations are quarantined', async () => {
        const worker = new CdpCyclotronDeadLetterWorker(
            { ...hub, CDP_QUARANTINE_ESCALATION_THRESHOLD: 1 },
            {
                ...createCdpConsumerDeps(hub),
                crashGuardSettings: {
                    valkey: createCrashGuardValkeyPool(hub),
                    mode: 'shadow',
                    maxAttempts: 3,
                    keyTtlSeconds: 60,
                    maxFlaggedPartitions: 32,
                    backgroundTaskTimeoutMs: 10_000,
                },
            },
            createMockJobQueue()
        )

        try {
            await expect(
                worker['quarantine'].quarantine([{ invocation: queued(), partition: 0, offset: 12 }])
            ).resolves.toBeUndefined()

            expect(mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_HOG_INVOCATION_RESULTS)).toHaveLength(1)
            const gauge = (await register.getSingleMetric('cdp_quarantined_functions')!.get()).values
            expect(gauge.filter((v) => v.labels.function_id === fn.id)).toEqual([
                expect.objectContaining({ labels: { function_id: fn.id, team_id: String(team.id) }, value: 1 }),
            ])
            expect((await worker.hogWatcher.getPersistedState(fn.id)).state).toEqual(HogWatcherState.healthy)
        } finally {
            worker['tracker']?.stop()
        }
    })
})
