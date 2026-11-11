import { createHash } from 'crypto'
import { Counter } from 'prom-client'

import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, HogFunctionType } from '../types'
import { createAddLogFunction } from '../utils'
import { createInvocationResult } from '../utils/invocation-utils'

const GEOIP_TEMPLATE_ID = 'template-geoip'

// sha256 of the trimmed source of each shipped GeoIP template version whose early return is the one
// geoipNoopResult mirrors. Saving a function trims its source, so the stored text is trimmed too.
// A function keeps the source it was saved with, so add every new version and never remove one.
const NOOP_SOURCE_HASHES = new Set([
    'c60a2c9cf0d2f82812392c3c682f4223e17082f109e02fbf5467fbb0069d0770', // shipped 2025-01-30
    '936b06d7d65914d43e5b9f45d8eecda36450e0c128bbfb522020fc0600261175', // shipped 2026-01-08
])

export const hogTransformationGeoipNoopSkips = new Counter({
    name: 'hog_transformation_geoip_noop_skips_total',
    help: 'GeoIP transformation invocations answered without the VM because the template returns the event unchanged',
})

const noopSourceByFunction = new WeakMap<HogFunctionType, boolean>()

function isSaveTrimmedChar(code: number): boolean {
    return code === 0x20 || code === 0x09 || code === 0x0d || code === 0x0a
}

function trimLikeSave(source: string): string {
    let start = 0
    let end = source.length
    while (start < end && isSaveTrimmedChar(source.charCodeAt(start))) {
        start++
    }
    while (end > start && isSaveTrimmedChar(source.charCodeAt(end - 1))) {
        end--
    }
    return source.slice(start, end)
}

function hasNoopSource(hogFunction: HogFunctionType): boolean {
    let matches = noopSourceByFunction.get(hogFunction)
    if (matches === undefined) {
        matches =
            typeof hogFunction.hog === 'string' &&
            NOOP_SOURCE_HASHES.has(createHash('sha256').update(trimLikeSave(hogFunction.hog)).digest('hex'))
        noopSourceByFunction.set(hogFunction, matches)
    }
    return matches
}

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
    if (hogFunction.template_id !== GEOIP_TEMPLATE_ID || !hasNoopSource(hogFunction)) {
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
