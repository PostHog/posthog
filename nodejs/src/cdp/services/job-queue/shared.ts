import { Histogram } from 'prom-client'

import { CyclotronJobInvocation } from '../../types'

export const cdpJobSizeKb = new Histogram({
    name: 'cdp_cyclotron_job_size_kb',
    help: 'The size in kb of the jobs we are processing',
    buckets: [0, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, Infinity],
    labelNames: ['queue_kind'],
})

export type SanitizeOptions = {
    stripGroups?: boolean
    stripPerson?: boolean
}

/**
 * Strip transient data (e.g. groups, person) from invocation state before persisting.
 * These are large and easily reloaded by the worker, so we avoid storing them.
 * Returns a new object if modifications are needed, otherwise the original.
 */
export function sanitizeInvocationForPersistence(
    invocation: CyclotronJobInvocation,
    options: SanitizeOptions = { stripGroups: true }
): CyclotronJobInvocation {
    const globals = invocation.state?.globals
    if (!globals) {
        return invocation
    }

    const shouldStripGroups = options.stripGroups && globals.groups && Object.keys(globals.groups).length > 0
    const shouldStripPerson = options.stripPerson && globals.person

    if (!shouldStripGroups && !shouldStripPerson) {
        return invocation
    }

    const { groups: _g, person: _p, ...restGlobals } = globals
    const newGlobals: typeof globals = { ...restGlobals }

    if (!shouldStripGroups && globals.groups) {
        newGlobals.groups = globals.groups
    }
    if (!shouldStripPerson && globals.person) {
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
