import Piscina from '@posthog/piscina'
import { PluginEvent } from '@posthog/plugin-scaffold/src/types'
import { Redis } from 'ioredis'
import * as nodeSchedule from 'node-schedule'

import {
    loadPluginSchedule,
    LOCKED_RESOURCE,
    runScheduleDebounced,
    startPluginSchedules,
    waitForTasksToFinish,
} from '../src/main/services/schedule'
import { Hub, LogLevel, PluginScheduleControl } from '../src/types'
import { createHub } from '../src/utils/db/hub'
import { delay } from '../src/utils/utils'
import { createPromise } from './helpers/promises'
import { resetTestDatabase } from './helpers/sql'
import { setupPiscina } from './helpers/worker'

jest.mock('../src/utils/db/sql')
jest.mock('../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

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

function numberOfScheduledJobs() {
    return Object.keys(nodeSchedule.scheduledJobs).length
}

describe('schedule', () => {
    test('runScheduleDebounced', async () => {
        const workerThreads = 1
        const testCode = `
        const counterKey = 'test_counter_2'
        async function setupPlugin (meta) {
            await meta.cache.set(counterKey, 0)
        }
        async function processEvent (event, meta) {
            event.properties['counter'] = await meta.cache.get(counterKey)
            return event
        }
        async function runEveryMinute (meta) {
            // stall for a second
            await new Promise(resolve => __jestSetTimeout(resolve, 500))
            await meta.cache.incr(counterKey)
        }
    `
        await resetTestDatabase(testCode)
        const piscina = setupPiscina(workerThreads, 10)
        const ingestEvent = async (event: PluginEvent) => {
            const result = await piscina.run({ task: 'runEventPipeline', args: { event } })
            const resultEvent = result.args[0]
            return resultEvent
        }

        const [hub, closeHub] = await createHub({ LOG_LEVEL: LogLevel.Log })
        hub.pluginSchedule = await loadPluginSchedule(piscina)
        expect(hub.pluginSchedule).toEqual({ runEveryDay: [], runEveryHour: [], runEveryMinute: [39] })

        const event1 = await ingestEvent(createEvent())
        expect(event1.properties['counter']).toBe(0)

        runScheduleDebounced(hub, piscina, 'runEveryMinute')
        runScheduleDebounced(hub, piscina, 'runEveryMinute')
        runScheduleDebounced(hub, piscina, 'runEveryMinute')
        await delay(100)

        const event2 = await ingestEvent(createEvent())
        expect(event2.properties['counter']).toBe(0)

        await delay(500)

        const event3 = await ingestEvent(createEvent())
        expect(event3.properties['counter']).toBe(1)

        await waitForTasksToFinish(hub)
        await delay(1000)
        await piscina.destroy()
        await closeHub()
    })

    test('runScheduleDebounced exception', async () => {
        const workerThreads = 2
        const testCode = `
        async function runEveryMinute (meta) {
            throw new Error('lol')
        }
    `
        await resetTestDatabase(testCode)
        const piscina = setupPiscina(workerThreads, 10)

        const [hub, closeHub] = await createHub({ LOG_LEVEL: LogLevel.Log })
        hub.pluginSchedule = await loadPluginSchedule(piscina)

        runScheduleDebounced(hub, piscina, 'runEveryMinute')

        await waitForTasksToFinish(hub)

        // nothing bad should have happened. the error is in SQL via setError, but that ran in another worker (can't mock)
        // and we're not testing it E2E so we can't check the DB either...

        try {
            await delay(1000)
            await piscina.destroy()
            await closeHub()
        } catch {}
    })

    describe('startPluginSchedules', () => {
        let hub: Hub, piscina: Piscina, closeHub: () => Promise<void>, redis: Redis

        beforeEach(async () => {
            const workerThreads = 2
            const testCode = `
            async function runEveryMinute (meta) {
                throw new Error('lol')
            }
        `
            await resetTestDatabase(testCode)
            piscina = setupPiscina(workerThreads, 10)
            ;[hub, closeHub] = await createHub({ LOG_LEVEL: LogLevel.Log, SCHEDULE_LOCK_TTL: 3 })

            redis = await hub.redisPool.acquire()
            await redis.del(LOCKED_RESOURCE)
        })

        afterEach(async () => {
            await redis.del(LOCKED_RESOURCE)
            await hub.redisPool.release(redis)
            await delay(1000)
            await piscina.destroy()
            await closeHub()
        })

        test('redlock', async () => {
            const promises = [createPromise(), createPromise(), createPromise()]
            let i = 0

            let lock1 = false
            let lock2 = false
            let lock3 = false

            const schedule1 = await startPluginSchedules(hub, piscina, () => {
                lock1 = true
                promises[i++].resolve()
            })

            await promises[0].promise

            expect(lock1).toBe(true)
            expect(lock2).toBe(false)
            expect(lock3).toBe(false)

            const schedule2 = await startPluginSchedules(hub, piscina, () => {
                lock2 = true
                promises[i++].resolve()
            })
            const schedule3 = await startPluginSchedules(hub, piscina, () => {
                lock3 = true
                promises[i++].resolve()
            })

            await schedule1.stopSchedule()

            await promises[1].promise

            expect(lock2 || lock3).toBe(true)

            if (lock3) {
                await schedule3.stopSchedule()
                await promises[2].promise
                expect(lock2).toBe(true)
                await schedule2.stopSchedule()
            } else {
                await schedule2.stopSchedule()
                await promises[2].promise
                expect(lock3).toBe(true)
                await schedule3.stopSchedule()
            }
        })

        describe('loading the schedule', () => {
            let schedule: PluginScheduleControl | null = null

            afterEach(async () => {
                await schedule?.stopSchedule()
                schedule = null
            })

            test('loads successfully', async () => {
                schedule = await startPluginSchedules(hub, piscina)

                expect(hub.pluginSchedule).toEqual({
                    runEveryMinute: [39],
                    runEveryHour: [],
                    runEveryDay: [],
                })

                await resetTestDatabase(`
                async function runEveryDay (meta) {
                    throw new Error('lol')
                }
            `)

                await schedule.reloadSchedule()

                expect(hub.pluginSchedule).toEqual({
                    runEveryMinute: [39],
                    runEveryHour: [],
                    runEveryDay: [],
                })
            })

            test('node-schedule tasks are created and removed on stop', async () => {
                expect(numberOfScheduledJobs()).toEqual(0)

                const schedule = await startPluginSchedules(hub, piscina)
                expect(numberOfScheduledJobs()).toEqual(3)

                nodeSchedule.scheduleJob('1 1 1 1 1', () => 1)
                expect(numberOfScheduledJobs()).toEqual(4)

                await schedule.stopSchedule()
                expect(numberOfScheduledJobs()).toEqual(0)
            })
        })
    })
})
