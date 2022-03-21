import Piscina from '@posthog/piscina'

import { defaultConfig } from '../../src/config/config'
import { LogLevel } from '../../src/types'
import { makePiscina } from '../../src/worker/piscina'

export function setupPiscina(workers: number, tasksPerWorker: number): Piscina {
    return makePiscina({
        ...defaultConfig,
        WORKER_CONCURRENCY: workers,
        TASKS_PER_WORKER: tasksPerWorker,
        LOG_LEVEL: LogLevel.Log,
    })
}
