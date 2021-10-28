import { PluginEvent } from '@posthog/plugin-scaffold/src/types'
import { DateTime } from 'luxon'
import * as os from 'os'
import { performance } from 'perf_hooks'

import { IEvent } from '../../src/config/idl/protos'
import { Hub, LogLevel, SessionRecordingEvent, Team } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { UUIDT } from '../../src/utils/utils'
import { EventsProcessor } from '../../src/worker/ingestion/process-event'
import { getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { endLog, startLog } from './helpers/log'
import { ingestCountEvents, setupPiscina } from './helpers/piscina'

jest.mock('../../src/utils/db/sql')
jest.setTimeout(600000) // 600 sec timeout

describe('ingestion benchmarks', () => {
    let team: Team
    let hub: Hub
    let closeHub: () => Promise<void>
    let eventsProcessor: EventsProcessor
    let now = DateTime.utc()

    async function processOneEvent(): Promise<IEvent | SessionRecordingEvent> {
        return await eventsProcessor.processEvent(
            'my_id',
            '127.0.0.1',
            'http://localhost',
            {
                event: 'default event',
                timestamp: now.toISO(),
                properties: { token: team.api_token },
            } as any as PluginEvent,
            team.id,
            now,
            now,
            new UUIDT().toString()
        )
    }

    beforeEach(async () => {
        await resetTestDatabase(`
            function processEvent (event, meta) {
                event.properties["somewhere"] = "in a benchmark";
                return event
            }
        `)
        ;[hub, closeHub] = await createHub({
            PLUGINS_CELERY_QUEUE: 'benchmark-plugins-celery-queue',
            CELERY_DEFAULT_QUEUE: 'benchmark-celery-default-queue',
            LOG_LEVEL: LogLevel.Log,
        })
        eventsProcessor = new EventsProcessor(hub)
        team = await getFirstTeam(hub)
        now = DateTime.utc()

        // warmup
        for (let i = 0; i < 5; i++) {
            await processOneEvent()
        }
    })

    afterEach(async () => {
        await closeHub?.()
    })

    test('basic sequential ingestion', async () => {
        const count = 3000

        startLog('Postgres', 'Await Ingested', 'event', 'events')

        for (let i = 0; i < count; i++) {
            await processOneEvent()
        }

        endLog(count)
    })

    test('basic parallel ingestion', async () => {
        const count = 3000
        const promises = []

        startLog('Postgres', 'Promise.all Ingested', 'event', 'events')

        for (let i = 0; i < count; i++) {
            promises.push(processOneEvent())
        }
        await Promise.all(promises)

        endLog(count)
    })

    test('piscina ingestion', async () => {
        const coreCount = os.cpus().length
        const workerThreads = [1, 2, 4, 8, 12, 16].filter((threads) => threads <= coreCount)
        const rounds = 1

        const events = 10000

        const result: Record<string, any> = {
            coreCount,
            events,
        }

        const results = []
        for (const threads of workerThreads) {
            await resetTestDatabase('const processEvent = e => e')
            const piscina = setupPiscina(threads, 10)

            // warmup
            await ingestCountEvents(piscina, threads * 4)

            // start
            const startTime = performance.now()
            for (let i = 0; i < rounds; i++) {
                await ingestCountEvents(piscina, events)
            }
            result[`${threads} thread${threads === 1 ? '' : 's'}`] = Math.round(
                1000 / ((performance.now() - startTime) / events / rounds)
            )

            await piscina.destroy()
            console.log(JSON.stringify({ result }, null, 2))
        }
        results.push(result)
        console.table(results)
    })
})
