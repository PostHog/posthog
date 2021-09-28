import Piscina from '@posthog/piscina'
import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import { defaultConfig } from '../../../src/config/config'
import { LogLevel } from '../../../src/types'
import { UUIDT } from '../../../src/utils/utils'
import { makePiscina } from '../../../src/worker/piscina'

export function setupPiscina(workers: number, tasksPerWorker: number): Piscina {
    return makePiscina({
        ...defaultConfig,
        WORKER_CONCURRENCY: workers,
        TASKS_PER_WORKER: tasksPerWorker,
        LOG_LEVEL: LogLevel.Log,
    })
}

export function ingestOneEvent(
    ingestEvent: (event: PluginEvent) => Promise<PluginEvent>,
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
        uuid: new UUIDT().toString(),
    }
    return ingestEvent(defaultEvent)
}

export async function ingestCountEvents(piscina: ReturnType<typeof makePiscina>, count: number): Promise<void> {
    const maxPromises = 500
    const promises = Array(maxPromises)
    const ingestEvent = (event: PluginEvent) => piscina.run({ task: 'ingestEvent', args: { event } })

    const groups = Math.ceil(count / maxPromises)
    for (let j = 0; j < groups; j++) {
        const groupCount = groups === 1 ? count : j === groups - 1 ? count % maxPromises : maxPromises
        for (let i = 0; i < groupCount; i++) {
            promises[i] = ingestOneEvent(ingestEvent, i)
        }
        await Promise.all(promises)
    }
}
