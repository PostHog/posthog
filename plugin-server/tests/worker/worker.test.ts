import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import { loadPluginSchedule } from '../../src/main/services/schedule'
import { Hub, PreIngestionEvent } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { KafkaProducerWrapper } from '../../src/utils/db/kafka-producer-wrapper'
import { delay, UUIDT } from '../../src/utils/utils'
import { ActionManager } from '../../src/worker/ingestion/action-manager'
import { ActionMatcher } from '../../src/worker/ingestion/action-matcher'
import { EventPipelineRunner } from '../../src/worker/ingestion/event-pipeline/runner'
import { runPluginTask } from '../../src/worker/plugins/run'
import { loadSchedule, setupPlugins } from '../../src/worker/plugins/setup'
import { teardownPlugins } from '../../src/worker/plugins/teardown'
import { createTaskRunner } from '../../src/worker/worker'
import { resetTestDatabase } from '../helpers/sql'
import { setupPiscina } from '../helpers/worker'

jest.mock('../../src/worker/ingestion/action-manager')
jest.mock('../../src/worker/ingestion/action-matcher')
jest.mock('../../src/utils/db/sql')
jest.mock('../../src/utils/status')
jest.mock('../../src/worker/plugins/run')
jest.mock('../../src/worker/plugins/setup')
jest.mock('../../src/worker/plugins/teardown')
jest.setTimeout(600000) // 600 sec timeout

function createEvent(index = 0): PluginEvent {
    return {
        distinct_id: 'my_id',
        ip: '127.0.0.1',
        site_url: 'http://localhost',
        team_id: 2,
        now: new Date().toISOString(),
        event: 'default event',
        properties: { key: 'value', index },
        uuid: new UUIDT().toString(),
    }
}

describe('worker', () => {
    beforeEach(() => {
        console.debug = jest.fn()
        jest.spyOn(ActionManager.prototype, 'reloadAllActions')
        jest.spyOn(ActionManager.prototype, 'reloadAction')
        jest.spyOn(ActionManager.prototype, 'dropAction')
        jest.spyOn(ActionMatcher.prototype, 'match')
    })

    test('piscina worker test', async () => {
        const workerThreads = 2
        const testCode = `
        function processEvent (event, meta) {
            event.properties["somewhere"] = "over the rainbow";
            return event
        }
        async function runEveryDay (meta) {
            return 4
        }
    `
        await resetTestDatabase(testCode)
        const piscina = setupPiscina(workerThreads, 10)

        const runEveryDay = (pluginConfigId: number) => piscina.run({ task: 'runEveryDay', args: { pluginConfigId } })
        const ingestEvent = async (event: PluginEvent) => {
            const result = await piscina.run({ task: 'runEventPipeline', args: { event } })
            const resultEvent = result.args[0]
            return { ...result, event: resultEvent }
        }

        const pluginSchedule = await loadPluginSchedule(piscina)
        expect(pluginSchedule).toEqual({ runEveryDay: [39], runEveryHour: [], runEveryMinute: [] })

        const ingestResponse1 = await ingestEvent(createEvent())
        expect(ingestResponse1.event.properties['somewhere']).toBe('over the rainbow')

        const everyDayReturn = await runEveryDay(39)
        expect(everyDayReturn).toBe(4)

        const ingestResponse2 = await ingestEvent(createEvent())
        expect(ingestResponse2).toEqual({
            lastStep: 'runAsyncHandlersStep',
            args: expect.anything(),
            event: expect.anything(),
        })

        const ingestResponse3 = await ingestEvent({ ...createEvent(), uuid: undefined })
        expect(ingestResponse3.error).toEqual('Not a valid UUID: "undefined"')

        await delay(2000)
        await piscina.destroy()
    })

    test('assume that the workerThreads and tasksPerWorker values behave as expected', async () => {
        const workerThreads = 2
        const tasksPerWorker = 3
        const testCode = `
        async function processEvent (event, meta) {
            await new Promise(resolve => __jestSetTimeout(resolve, 300))
            return event
        }
    `
        await resetTestDatabase(testCode)
        const piscina = setupPiscina(workerThreads, tasksPerWorker)
        const processEvent = (event: PluginEvent) => piscina.run({ task: '_testsRunProcessEvent', args: { event } })
        const promises: Array<Promise<any>> = []

        // warmup 2x
        await Promise.all([processEvent(createEvent()), processEvent(createEvent())])

        // process 10 events in parallel and ignore the result
        for (let i = 0; i < 10; i++) {
            promises.push(processEvent(createEvent(i)))
        }
        await delay(100)
        expect(piscina.queueSize).toBe(10 - workerThreads * tasksPerWorker)
        expect(piscina.completed).toBe(0 + 2)
        await delay(300)
        expect(piscina.queueSize).toBe(0)
        expect(piscina.completed).toBe(workerThreads * tasksPerWorker + 2)
        await delay(300)
        expect(piscina.queueSize).toBe(0)
        expect(piscina.completed).toBe(10 + 2)

        try {
            await piscina.destroy()
        } catch {}
    })

    describe('createTaskRunner()', () => {
        let taskRunner: any
        let hub: Hub
        let closeHub: () => Promise<void>

        beforeEach(async () => {
            ;[hub, closeHub] = await createHub()
            taskRunner = createTaskRunner(hub)
        })
        afterEach(async () => {
            await closeHub()
        })

        it('handles `getPluginSchedule` task', async () => {
            hub.pluginSchedule = { runEveryDay: [66] }

            expect(await taskRunner({ task: 'getPluginSchedule' })).toEqual(hub.pluginSchedule)
        })

        it('handles `runEventPipeline` tasks', async () => {
            const spy = jest
                .spyOn(EventPipelineRunner.prototype, 'runEventPipeline')
                .mockResolvedValue('runEventPipeline result' as any)
            const event = createEvent()

            expect(await taskRunner({ task: 'runEventPipeline', args: { event } })).toEqual('runEventPipeline result')

            expect(spy).toHaveBeenCalledWith(event)
        })

        it('handles `runBufferEventPipeline` tasks', async () => {
            const spy = jest
                .spyOn(EventPipelineRunner.prototype, 'runBufferEventPipeline')
                .mockResolvedValue('runBufferEventPipeline result' as any)
            const event: PreIngestionEvent = {
                eventUuid: 'uuid1',
                distinctId: 'my_id',
                ip: '127.0.0.1',
                teamId: 2,
                timestamp: '2020-02-23T02:15:00Z',
                event: '$pageview',
                properties: {},
                elementsList: [],
            }

            expect(await taskRunner({ task: 'runBufferEventPipeline', args: { event } })).toEqual(
                'runBufferEventPipeline result'
            )

            expect(spy).toHaveBeenCalledWith(event)
        })

        it('handles `runEvery` tasks', async () => {
            jest.mocked(runPluginTask).mockImplementation((server, task, taskType, pluginId) =>
                Promise.resolve(`${task} for ${pluginId}`)
            )

            expect(await taskRunner({ task: 'runEveryMinute', args: { pluginConfigId: 1 } })).toEqual(
                'runEveryMinute for 1'
            )
            expect(await taskRunner({ task: 'runEveryHour', args: { pluginConfigId: 1 } })).toEqual(
                'runEveryHour for 1'
            )
            expect(await taskRunner({ task: 'runEveryDay', args: { pluginConfigId: 1 } })).toEqual('runEveryDay for 1')
        })

        it('handles `reloadPlugins` task', async () => {
            await taskRunner({ task: 'reloadPlugins', args: { pluginRows: [] } })

            expect(setupPlugins).toHaveBeenCalledWith(hub, [])
        })

        it('handles `reloadSchedule` task', async () => {
            await taskRunner({ task: 'reloadSchedule' })

            expect(loadSchedule).toHaveBeenCalled()
        })

        it('handles `reloadAllActions` task', async () => {
            await taskRunner({ task: 'reloadAllActions' })

            expect(hub.actionManager.reloadAllActions).toHaveBeenCalledWith()
        })

        it('handles `reloadAction` task', async () => {
            await taskRunner({ task: 'reloadAction', args: { teamId: 2, actionId: 777 } })

            expect(hub.actionManager.reloadAction).toHaveBeenCalledWith(2, 777)
        })

        it('handles `dropAction` task', async () => {
            await taskRunner({ task: 'dropAction', args: { teamId: 2, actionId: 777 } })

            expect(hub.actionManager.dropAction).toHaveBeenCalledWith(2, 777)
        })

        it('handles `teardownPlugin` task', async () => {
            await taskRunner({ task: 'teardownPlugins' })

            expect(teardownPlugins).toHaveBeenCalled()
        })

        it('handles `flushKafkaMessages` task', async () => {
            hub.kafkaProducer = { flush: jest.fn() } as unknown as KafkaProducerWrapper

            await taskRunner({ task: 'flushKafkaMessages' })

            expect(hub.kafkaProducer.flush).toHaveBeenCalled()
        })
    })
})
