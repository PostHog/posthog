import { Histogram } from 'prom-client'

import { CyclotronJobInvocation } from '../../types'

export const cdpJobSizeKb = new Histogram({
    name: 'cdp_cyclotron_job_size_kb',
    help: 'The size in kb of the jobs we are processing',
    buckets: [0, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, Infinity],
    labelNames: ['queue_kind'],
})

export const cdpJobSizeCompressedKb = new Histogram({
    name: 'cdp_cyclotron_job_size_compressed_kb',
    help: 'The size in kb of the compressed jobs we are processing',
    buckets: [0, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, Infinity],
    labelNames: ['queue_kind'],
})

/**
 * Strip transient data (e.g. groups) from invocation state before persisting.
 * Groups are large and easily reloaded by the worker, so we avoid storing them.
 * Returns a new object if modifications are needed, otherwise the original.
 */
export function sanitizeInvocationForPersistence(invocation: CyclotronJobInvocation): CyclotronJobInvocation {
    const groups = invocation.state?.globals?.groups
    if (groups && Object.keys(groups).length > 0) {
        const { groups: _, ...globalsWithoutGroups } = invocation.state!.globals
        return {
            ...invocation,
            state: {
                ...invocation.state,
                globals: globalsWithoutGroups,
            },
        }
    }
    return invocation
}
