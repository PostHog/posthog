import { Histogram } from 'prom-client'

import { CyclotronJobInvocation } from '../../types'

export const cdpJobSizeKb = new Histogram({
    name: 'cdp_job_size_kb',
    help: 'The size in kb of the jobs we are processing',
    buckets: [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity],
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
