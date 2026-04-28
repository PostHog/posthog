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
 * Strip transient data from invocation state before persisting.
 * Groups are always stripped. Person is stripped when stripPerson is true.
 * These are large and easily reloaded by the worker, so we avoid storing them.
 * Returns a new object if modifications are needed, otherwise the original.
 */
export function sanitizeInvocationForPersistence(
    invocation: CyclotronJobInvocation,
    { stripPerson }: { stripPerson?: boolean } = {}
): CyclotronJobInvocation {
    const globals = invocation.state?.globals
    if (!globals) {
        return invocation
    }

    const hasGroups = globals.groups && Object.keys(globals.groups).length > 0
    const hasPerson = stripPerson && globals.person

    if (!hasGroups && !hasPerson) {
        return invocation
    }

    const { groups: _g, person: _p, ...restGlobals } = globals
    const newGlobals: typeof globals = { ...restGlobals }

    if (!hasPerson && globals.person) {
        newGlobals.person = globals.person
    }

    return {
        ...invocation,
        state: {
            ...invocation.state,
            globals: newGlobals,
        },
    }
}
