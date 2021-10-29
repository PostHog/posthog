import { PluginEvent } from '@posthog/plugin-scaffold/src/types'
import * as os from 'os'
import { performance } from 'perf_hooks'

import { defaultConfig } from '../../src/config/config'
import { LogLevel } from '../../src/types'
import { makePiscina } from '../../src/worker/piscina'
import { resetTestDatabase } from '../../tests/helpers/sql'

jest.mock('../../src/utils/db/sql')
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

async function processCountEvents(piscina: ReturnType<typeof makePiscina>, count: number, batchSize = 1) {
    const maxPromises = 1000
    const promises = Array(maxPromises)
    const processEvent = (event: PluginEvent) => piscina.run({ task: 'processEvent', args: { event } })

    const groups = Math.ceil((count * batchSize) / maxPromises)
    for (let j = 0; j < groups; j++) {
        const groupCount = groups === 1 ? count : j === groups - 1 ? (count * batchSize) % maxPromises : maxPromises
        for (let i = 0; i < groupCount; i++) {
            promises[i] = processOneEvent(processEvent, i)
        }
        await Promise.all(promises)
    }
}

function setupPiscina(workers: number, tasksPerWorker: number) {
    return makePiscina({
        ...defaultConfig,
        WORKER_CONCURRENCY: workers,
        TASKS_PER_WORKER: tasksPerWorker,
        LOG_LEVEL: LogLevel.Log,
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
            events: 5000,
            testCode: `
                function processEvent (event, meta) {
                    event.properties = { "somewhere": "over the rainbow" };
                    return event
                }
            `,
        },
        {
            // used to be 'for200k', but since we inject Date.now() code into
            // the for/while/do loops, to throw if they are too long, running
            // those comparisons 200k * 10k * runs * threads times is bit too much
            testName: 'for2k',
            events: 5000,
            testCode: `
                function processEvent (event, meta) {
                    let j = 0; for(let i = 0; i < 2000; i++) { j = i };
                    event.properties = { "somewhere": "over the rainbow" };
                    return event
                }
            `,
        },
        {
            testName: 'timeout100ms',
            events: 5000,
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
        await resetTestDatabase(testCode)
        const events = isLightDevRun ? _events / 10 : _events
        for (const batchSize of [1, 10, 100].filter((size) => size <= events)) {
            const result: Record<string, any> = {
                testName,
                coreCount,
                events,
                batchSize,
            }
            for (const threads of workerThreads) {
                const piscina = setupPiscina(threads, 100)

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
