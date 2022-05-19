import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import { loadPluginSchedule } from '../../src/main/services/schedule'
import { Hub } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { KafkaProducerWrapper } from '../../src/utils/db/kafka-producer-wrapper'
import { delay, UUIDT } from '../../src/utils/utils'
import { ActionManager } from '../../src/worker/ingestion/action-manager'
import { ActionMatcher } from '../../src/worker/ingestion/action-matcher'
import { ingestEvent } from '../../src/worker/ingestion/ingest-event'
import { runPluginTask, runProcessEvent } from '../../src/worker/plugins/run'
import { loadSchedule, setupPlugins } from '../../src/worker/plugins/setup'
import { teardownPlugins } from '../../src/worker/plugins/teardown'
import { createTaskRunner } from '../../src/worker/worker'
import { resetTestDatabase } from '../helpers/sql'
import { setupPiscina } from '../helpers/worker'

jest.mock('../../src/worker/ingestion/action-manager')
jest.mock('../../src/worker/ingestion/action-matcher')
jest.mock('../../src/utils/db/sql')
jest.mock('../../src/utils/status')
jest.mock('../../src/worker/ingestion/ingest-event')
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

        const processEvent = (event: PluginEvent) => piscina.run({ task: 'processEvent', args: { event } })
        const runEveryDay = (pluginConfigId: number) => piscina.run({ task: 'runEveryDay', args: { pluginConfigId } })
        const ingestEvent = (event: PluginEvent) => piscina.run({ task: 'ingestEvent', args: { event } })

        const pluginSchedule = await loadPluginSchedule(piscina)
        expect(pluginSchedule).toEqual({ runEveryDay: [39], runEveryHour: [], runEveryMinute: [] })

        const event = await processEvent(createEvent())
        expect(event.properties['somewhere']).toBe('over the rainbow')

        const everyDayReturn = await runEveryDay(39)
        expect(everyDayReturn).toBe(4)

        const ingestResponse1 = await ingestEvent(createEvent())
        expect(ingestResponse1).toEqual({ success: false, error: 'Not a valid UUID: "undefined"' })

        const ingestResponse2 = await ingestEvent({ ...createEvent(), uuid: new UUIDT().toString() })
        expect(ingestResponse2).toEqual({ success: true, actionMatches: [], preIngestionEvent: expect.anything() })

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
        const processEvent = (event: PluginEvent) => piscina.run({ task: 'processEvent', args: { event } })
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

        it('handles `processEvent` task', async () => {
            jest.mocked(runProcessEvent).mockReturnValue('runProcessEvent response' as any)

            expect(await taskRunner({ task: 'processEvent', args: { event: 'someEvent' } })).toEqual(
                'runProcessEvent response'
            )

            expect(runProcessEvent).toHaveBeenCalledWith(hub, 'someEvent')
        })

        it('handles `getPluginSchedule` task', async () => {
            hub.pluginSchedule = { runEveryDay: [66] }

            expect(await taskRunner({ task: 'getPluginSchedule' })).toEqual(hub.pluginSchedule)
        })

        it('handles `ingestEvent` task', async () => {
            jest.mocked(ingestEvent).mockReturnValue('ingestEvent response' as any)

            expect(await taskRunner({ task: 'ingestEvent', args: { event: 'someEvent' } })).toEqual(
                'ingestEvent response'
            )

            expect(ingestEvent).toHaveBeenCalledWith(hub, 'someEvent')
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
            await taskRunner({ task: 'reloadPlugins' })

            expect(setupPlugins).toHaveBeenCalled()
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
