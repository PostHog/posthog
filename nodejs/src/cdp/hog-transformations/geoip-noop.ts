import { Counter } from 'prom-client'

import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { createAddLogFunction } from '../utils'
import { createInvocationResult } from '../utils/invocation-utils'
import { programKey } from './rust-vm'

const GEOIP_TEMPLATE_ID = 'template-geoip'

// programKey of the shipped template code compiled by bin/hoge. Any other bytecode, such as an edited
// copy, runs on the VM. Change this key only after checking that geoipNoopResult still mirrors the
// template's early return.
const GEOIP_TEMPLATE_PROGRAM_KEY = 'D04pD8PYRIxwn7H63+foEYQyRfWkXjmsrPDwuPIdhM4='

export const hogTransformationGeoipNoopSkips = new Counter({
    name: 'hog_transformation_geoip_noop_skips_total',
    help: 'GeoIP transformation invocations answered without the VM because the template returns the event unchanged',
})

// Hog's empty(), identical in the Node and Rust VMs.
function isHogEmpty(value: unknown): boolean {
    if (value === null || value === undefined) {
        return true
    }
    if (typeof value === 'string' || Array.isArray(value)) {
        return value.length === 0
    }
    if (typeof value === 'object') {
        return Object.keys(value).length === 0
    }
    return false
}

/**
 * The result the GeoIP template produces when it returns the event unchanged, or null when the VM
 * must run it. Mirrors the template's `$geoip_disable or empty($ip)` early return.
 */
export function geoipNoopResult(
    invocation: CyclotronJobInvocationHogFunction
): CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> | null {
    const startedAt = performance.now()
    const { hogFunction } = invocation
    if (
        hogFunction.template_id !== GEOIP_TEMPLATE_ID ||
        programKey(hogFunction.bytecode) !== GEOIP_TEMPLATE_PROGRAM_KEY
    ) {
        return null
    }

    const event = invocation.state.globals.event
    if (!event.properties.$geoip_disable && !isHogEmpty(event.properties.$ip)) {
        return null
    }

    hogTransformationGeoipNoopSkips.inc()
    const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation, {}, { execResult: event })
    const addLog = createAddLogFunction(result.logs)
    addLog('info', 'geoip disabled or no ip.')
    addLog('debug', `Function completed in ${Number((performance.now() - startedAt).toFixed(2))}ms.`)
    return result
}
