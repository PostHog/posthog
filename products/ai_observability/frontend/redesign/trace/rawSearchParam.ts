import { TRACE_DRAWER_PARAMS } from './traceDrawerRows'

// kea-router reads a numeric param as a number, which turns a typed `1.50` into `1.5`. It also pads a value shaped like
// a JSON array or object with one space, so it reads that value back as a string.
export function rawSearchParam(search: string, name: string): string | null {
    const value = new URLSearchParams(search).get(name)
    if (!value) {
        return null
    }
    return /^(\[.*\]|\{.*\}) +$/.test(value) ? value.slice(0, -1) : value
}

// kea-router loses the text of a number or boolean, so a typed `1.50` must stay raw. A JSON param such as `filters` must
// stay parsed, because kea-router pads a string shaped like JSON and reads it back as a string. The drawer's own params
// are ids and `trace_search` is typed text, so they stay raw whatever their shape.
function keepsRawText(name: string, value: unknown): boolean {
    return (
        TRACE_DRAWER_PARAMS.includes(name) ||
        name === 'trace_search' ||
        typeof value === 'number' ||
        typeof value === 'boolean'
    )
}

/** The router's params with the text the URL holds, for a logic that writes them back with its own changes. */
export function withRawParams(searchParams: Record<string, unknown>, search: string): Record<string, unknown> {
    return Object.fromEntries(
        Object.entries(searchParams).map(([name, value]) => [
            name,
            keepsRawText(name, value) ? (rawSearchParam(search, name) ?? value) : value,
        ])
    )
}

export interface RouterUrl {
    location: { pathname: string; search: string }
    searchParams: Record<string, unknown>
    hashParams: Record<string, unknown>
}

/**
 * The router's `push` or `replace` arguments for the current URL with `changes` applied, keeping every other param as
 * typed. Call it as `router.actions.replace(...currentUrlWith(router.values, changes))`.
 */
export function currentUrlWith(
    { location, searchParams, hashParams }: RouterUrl,
    changes: Record<string, unknown>
): [string, Record<string, unknown>, Record<string, unknown>] {
    return [location.pathname, { ...withRawParams(searchParams, location.search), ...changes }, hashParams]
}
