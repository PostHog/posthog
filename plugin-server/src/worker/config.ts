import { TaskQueue } from '@posthog/piscina/src/common'

import { PluginsServerConfig } from '../types'

// Copy From: node_modules/piscina/src/index.ts -- copied because it's not exported
export interface PiscinaOptions {
    filename?: string | null
    minThreads?: number
    maxThreads?: number
    idleTimeout?: number
    maxQueue?: number | 'auto'
    concurrentTasksPerWorker?: number
    useAtomics?: boolean
    resourceLimits?: any
    argv?: string[]
    execArgv?: string[]
    env?: any
    workerData?: any
    taskQueue?: TaskQueue
    niceIncrement?: number
    trackUnmanagedFds?: boolean
    atomicsTimeout?: number
}

export function createConfig(serverConfig: PluginsServerConfig, filename: string): PiscinaOptions {
    const config: PiscinaOptions = {
        filename,
        workerData: { serverConfig },
        resourceLimits: {
            stackSizeMb: 10,
        },
        useAtomics: serverConfig.PISCINA_USE_ATOMICS,
        atomicsTimeout: serverConfig.PISCINA_ATOMICS_TIMEOUT,
    }

    if (serverConfig.WORKER_CONCURRENCY && serverConfig.WORKER_CONCURRENCY > 0) {
        config.minThreads = serverConfig.WORKER_CONCURRENCY
        config.maxThreads = serverConfig.WORKER_CONCURRENCY
    }

    if (serverConfig.TASKS_PER_WORKER > 1) {
        config.concurrentTasksPerWorker = serverConfig.TASKS_PER_WORKER
    }

    return config
}
