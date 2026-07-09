/** Generic / network / console value scrubs over parsed JSON (Custom and Plugin payloads). */
import { ScrubContext, isObject } from './config'
import { ScrubResult, scrubText } from './text'
import { scrubUrl } from './url'

const NETWORK_BODY_FIELDS = ['requestBody', 'responseBody']
const NETWORK_HEADER_FIELDS = ['requestHeaders', 'responseHeaders']
const CONSOLE_FIELDS = ['payload', 'trace']

type ScrubFn = (ctx: ScrubContext, s: string) => ScrubResult

function looksLikeUrl(s: string): boolean {
    return s.startsWith('http://') || s.startsWith('https://')
}

function scrubStringLeaf(ctx: ScrubContext, s: string): ScrubResult {
    return looksLikeUrl(s) ? scrubUrl(ctx, s) : scrubText(ctx, s)
}

/** Scrub `container[key]` if it is a string, writing back on change. */
function scrubFieldWith(ctx: ScrubContext, container: any, key: string | number, scrub: ScrubFn): boolean {
    const value = container[key]
    if (typeof value !== 'string') {
        return false
    }
    const result = scrub(ctx, value)
    if (result.changed) {
        container[key] = result.value
        return true
    }
    return false
}

/** Scrub `container[key]`: a string leaf (with writeback), otherwise recurse into it. */
function scrubChild(ctx: ScrubContext, container: any, key: string | number): boolean {
    const value = container[key]
    if (typeof value !== 'string') {
        return scrubValueInPlace(ctx, value)
    }
    const result = scrubStringLeaf(ctx, value)
    if (result.changed) {
        container[key] = result.value
        return true
    }
    return false
}

/** Recursively scrub string leaves inside an array/object, mutating in place. */
export function scrubValueInPlace(ctx: ScrubContext, value: unknown): boolean {
    let changed = false
    if (Array.isArray(value)) {
        for (let i = 0; i < value.length; i++) {
            changed = scrubChild(ctx, value, i) || changed
        }
    } else if (isObject(value)) {
        for (const key of Object.keys(value)) {
            changed = scrubChild(ctx, value, key) || changed
        }
    }
    return changed
}

/** Generic scrub of `owner[key]`, handling both a string leaf and a container. */
export function scrubGenericField(ctx: ScrubContext, owner: Record<string, unknown>, key: string): boolean {
    return scrubChild(ctx, owner, key)
}

/**
 * rrweb/network@1 payload at `owner[key]`: `{ requests: CapturedNetworkRequest[] }`.
 * Per request: `name` is a Resource Timing URL (URL-scrub); request/response
 * bodies and every header value are free text. Falls back to the generic field
 * scrub if the shape is off.
 */
export function scrubNetworkPlugin(ctx: ScrubContext, owner: Record<string, unknown>, key: string): boolean {
    const payload = owner[key]
    if (!isObject(payload)) {
        return scrubGenericField(ctx, owner, key)
    }
    const reqs = payload.requests
    if (!Array.isArray(reqs)) {
        return false
    }
    let changed = false
    for (const req of reqs) {
        if (!isObject(req)) {
            continue
        }
        changed = scrubFieldWith(ctx, req, 'name', scrubUrl) || changed
        for (const field of NETWORK_BODY_FIELDS) {
            changed = scrubFieldWith(ctx, req, field, scrubText) || changed
        }
        for (const field of NETWORK_HEADER_FIELDS) {
            const hdrs = req[field]
            if (isObject(hdrs)) {
                for (const k of Object.keys(hdrs)) {
                    changed = scrubFieldWith(ctx, hdrs, k, scrubText) || changed
                }
            }
        }
    }
    return changed
}

/** rrweb/console@1 payload at `owner[key]`: `{ level, payload: string[], trace: string[] }`. */
export function scrubConsolePlugin(ctx: ScrubContext, owner: Record<string, unknown>, key: string): boolean {
    const payload = owner[key]
    if (!isObject(payload)) {
        return scrubGenericField(ctx, owner, key)
    }
    let changed = false
    for (const field of CONSOLE_FIELDS) {
        const arr = payload[field]
        if (Array.isArray(arr)) {
            for (let i = 0; i < arr.length; i++) {
                // Console frames can hold URLs (stack traces); scrub URL-aware, not as plain text.
                changed = scrubFieldWith(ctx, arr, i, scrubStringLeaf) || changed
            }
        }
    }
    return changed
}
