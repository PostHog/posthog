import Piscina from '@posthog/piscina'

import { defaultConfig } from '../../src/config/config'
import { LogLevel } from '../../src/types'
import { makePiscina } from '../../src/worker/piscina'
import { PluginServerMode } from './../../src/types'

export function setupPiscina(
    workers: number,
    tasksPerWorker: number,
    pluginServerMode: PluginServerMode = PluginServerMode.Ingestion
): Piscina {
    return makePiscina({
        ...defaultConfig,
        WORKER_CONCURRENCY: workers,
        TASKS_PER_WORKER: tasksPerWorker,
        LOG_LEVEL: LogLevel.Log,
        SERVER_MODE: pluginServerMode,
    })
}
