import { makePiscina } from '../src/worker/piscina'
import { defaultConfig } from '../src/config'
import { PluginEvent } from 'posthog-plugins/src/types'
import { performance } from 'perf_hooks'
import { mockJestWithIndex } from '../tests/helpers/plugins'
import * as os from 'os'
import { LogLevel } from '../src/types'

jest.mock('../src/sql')
jest.setTimeout(600000) // 600 sec timeout

function processOneEvent(
    processEvent: (event: PluginEvent) => Promise<PluginEvent>,
    index: number
): Promise<PluginEvent> {
    const defaultEvent = {
        distinct_id: 'my_id',
        ip: '127.0.0.1',
        site_url: 'http://localhost',
        team_id: 2,
        now: new Date().toISOString(),
        event: 'default event',
        properties: { key: 'value', index },
    }

    return processEvent(defaultEvent)
}

function processOneBatch(
    processEventBatch: (batch: PluginEvent[]) => Promise<PluginEvent[]>,
    batchSize: number,
    batchIndex: number
): Promise<PluginEvent[]> {
    const events = [...Array(batchSize)].map((_, i) => ({
        distinct_id: 'my_id',
        ip: '127.0.0.1',
        site_url: 'http://localhost',
        team_id: 2,
        now: new Date().toISOString(),
        event: 'default event',
        properties: { key: 'value', batchIndex, indexInBatch: i },
    }))

    return processEventBatch(events)
}

async function processCountEvents(piscina: ReturnType<typeof makePiscina>, count: number, batchSize = 1) {
    const maxPromises = 1000
    const promises = Array(maxPromises)
    const processEvent = (event: PluginEvent) => piscina.runTask({ task: 'processEvent', args: { event } })
    const processEventBatch = (batch: PluginEvent[]) => piscina.runTask({ task: 'processEventBatch', args: { batch } })

    const groups = Math.ceil(count / maxPromises)
    for (let j = 0; j < groups; j++) {
        const groupCount = groups === 1 ? count : j === groups - 1 ? count % maxPromises : maxPromises
        for (let i = 0; i < groupCount; i++) {
            promises[i] =
                batchSize === 1 ? processOneEvent(processEvent, i) : processOneBatch(processEventBatch, batchSize, i)
        }
        await Promise.all(promises)
    }
}

function setupPiscina(workers: number, code: string, tasksPerWorker: number) {
    return makePiscina({
        ...defaultConfig,
        WORKER_CONCURRENCY: workers,
        TASKS_PER_WORKER: tasksPerWorker,
        LOG_LEVEL: LogLevel.Log,
        __jestMock: mockJestWithIndex(code),
    })
}

test('piscina worker benchmark', async () => {
    // Uncomment this to become a 10x developer and make the test run just as fast!
    // Reduces events by 10x and limits threads to max 8 for quicker development
    const isLightDevRun = false

    const coreCount = os.cpus().length
    const workerThreads = [1, 2, 4, 8, 12, 16].filter((threads) =>
        isLightDevRun ? threads <= 8 : threads <= coreCount
    )
    const rounds = 1

    const tests: { testName: string; events: number; testCode: string }[] = [
        {
            testName: 'simple',
            events: 10000,
            testCode: `
                function processEvent (event, meta) {
                    event.properties = { "somewhere": "over the rainbow" };
                    return event
                }
            `,
        },
        {
            testName: 'for200k',
            events: 10000,
            testCode: `
                function processEvent (event, meta) {
                    let j = 0; for(let i = 0; i < 200000; i++) { j = i };
                    event.properties = { "somewhere": "over the rainbow" };
                    return event
                }
            `,
        },
        {
            testName: 'timeout100ms',
            events: 10000,
            testCode: `
                async function processEvent (event, meta) {
                    await new Promise(resolve => __jestSetTimeout(() => resolve(), 100))
                    event.properties = { "somewhere": "over the rainbow" };
                    return event             
                }
            `,
        },
    ]

    const results: Array<Record<string, string | number>> = []
    for (const { testName, events: _events, testCode } of tests) {
        const events = isLightDevRun ? _events / 10 : _events
        for (const batchSize of [1, 10, 100].filter((size) => size <= events)) {
            const result: Record<string, any> = {
                testName,
                coreCount,
                events,
                batchSize,
            }
            for (const threads of workerThreads) {
                const piscina = setupPiscina(threads, testCode, 100)

                // warmup
                await processCountEvents(piscina, threads * 4)

                // start
                const startTime = performance.now()
                for (let i = 0; i < rounds; i++) {
                    await processCountEvents(piscina, events / batchSize, batchSize)
                }
                result[`${threads} thread${threads === 1 ? '' : 's'}`] = Math.round(
                    1000 / ((performance.now() - startTime) / events / rounds)
                )

                await piscina.destroy()
            }
            results.push(result)
            console.log(JSON.stringify({ result }, null, 2))
        }
    }
    console.table(results)
})
