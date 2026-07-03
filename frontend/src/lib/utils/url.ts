import { dayjs } from 'lib/dayjs'
import { stringifyWithBigInts } from 'lib/utils/json'

export function toParams(obj: Record<string, any>, explodeArrays: boolean = false): string {
    if (!obj) {
        return ''
    }

    function handleVal(val: any): string {
        if (dayjs.isDayjs(val)) {
            return encodeURIComponent(val.format('YYYY-MM-DD'))
        }
        val = typeof val === 'object' ? stringifyWithBigInts(val) : val
        return encodeURIComponent(val)
    }

    return Object.entries(obj)
        .filter((item) => item[1] != undefined && item[1] != null)
        .reduce(
            (acc, [key, val]) => {
                /**
                 *  query parameter arrays can be handled in two ways
                 *  either they are encoded as a single query parameter
                 *    a=[1, 2] => a=%5B1%2C2%5D
                 *  or they are "exploded" so each item in the array is sent separately
                 *    a=[1, 2] => a=1&a=2
                 **/
                if (explodeArrays && Array.isArray(val)) {
                    val.forEach((v) => acc.push([key, v]))
                } else {
                    acc.push([key, val])
                }

                return acc
            },
            [] as [string, any][]
        )
        .map(([key, val]) => `${key}=${handleVal(val)}`)
        .join('&')
}

export function fromParamsGivenUrl(url: string): Record<string, any> {
    return !url
        ? {}
        : url
              .replace(/^\?/, '')
              .split('&')
              .reduce(
                  (paramsObject, paramString) => {
                      const [key, value] = paramString.split('=')
                      paramsObject[key] = decodeURIComponent(value)
                      return paramsObject
                  },
                  {} as Record<string, any>
              )
}

export function fromParams(): Record<string, any> {
    return fromParamsGivenUrl(window.location.search)
}

export function tryDecodeURIComponent(value: string): string {
    try {
        return decodeURIComponent(value)
    } catch {
        return value
    }
}

// Parse a tags filter value coming from URL search params.
// Supports:
// - Repeated params handled upstream and aggregated as an array
// - JSON array string (e.g. "[\"a\",\"b\"]")
// - Comma-separated string (e.g. "a,b")
export function parseTagsFilter(raw: unknown): string[] | undefined {
    if (Array.isArray(raw)) {
        return (raw as unknown[]).map((v) => String(v)).filter(Boolean)
    }
    if (typeof raw === 'string') {
        // Try JSON first
        try {
            const parsed = JSON.parse(raw)
            if (Array.isArray(parsed)) {
                return parsed.map((v) => String(v)).filter(Boolean)
            }
        } catch {
            // Fall through to comma-separated
        }
        return raw
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
    }
    return undefined
}

/** Parse a URL/query param into a list of numeric IDs. Accepts an array, a JSON-encoded list, or a comma-separated string. */
export function parseNumericArrayFilter(raw: unknown): number[] | undefined {
    const toNumbers = (values: unknown[]): number[] => values.map((v) => Number(v)).filter((n) => Number.isFinite(n))

    let values: unknown[] | undefined

    if (Array.isArray(raw)) {
        values = raw
    } else if (typeof raw === 'number') {
        values = [raw]
    } else if (typeof raw === 'string') {
        const text = raw.trim()
        if (text.startsWith('[')) {
            try {
                const parsed = JSON.parse(text)
                values = Array.isArray(parsed) ? parsed : [parsed]
            } catch {
                // Looks like a JSON list but doesn't parse — treat as no valid IDs rather than
                // comma-splitting, which would half-apply malformed input (e.g. "[1,2" -> [2]).
                return undefined
            }
        } else {
            values = text.split(',').map((s) => s.trim())
        }
    }

    if (!values) {
        return undefined
    }

    const numbers = toNumbers(values.filter((v) => v !== '' && v !== null && v !== undefined))
    return numbers.length ? numbers : undefined
}

export function stripHTTP(url: string): string {
    url = url.replace(/(^[0-9]+_)/, '')
    url = url.replace(/(^\w+:|^)\/\//, '')
    return url
}

export function isDomain(url: string | URL): boolean {
    try {
        const parsedUrl = typeof url === 'string' ? new URL(url) : url
        if (parsedUrl.protocol.includes('http') && (!parsedUrl.pathname || parsedUrl.pathname === '/')) {
            return true
        }
        if (!parsedUrl.pathname.replace(/^\/\//, '').includes('/')) {
            return true
        }
    } catch {
        return false
    }
    return false
}

export function isURL(input: any): boolean {
    if (!input || typeof input !== 'string') {
        return false
    }
    const regexp = /^(http|capacitor|https):\/\/[\w*.-]+[\w*.-]+[\w\-._~:/?#[\]@%!$&'()*+,;=]+$/
    return !!input.trim().match(regexp)
}

export function isExternalLink(input: any): boolean {
    if (!input || typeof input !== 'string') {
        return false
    }
    const regexp = /^(https?:|mailto:|\/api\/)/
    return !!input.trim().match(regexp)
}

export function isEmail(string: string, options?: { requireTLD?: boolean }): boolean {
    if (!string) {
        return false
    }
    // https://html.spec.whatwg.org/multipage/input.html#valid-e-mail-address
    const regexp = options?.requireTLD
        ? /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$/
        : /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/
    return !!string.match?.(regexp)
}

export function parseGithubRepoURL(url: string): Record<string, string> {
    const match = url.match(
        /^https?:\/\/(?:www\.)?github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)(\/(commit|tree|releases\/tag)\/([A-Za-z0-9_.\-/]+))?/
    )

    if (!match) {
        throw new Error(`${url} is not a valid GitHub URL`)
    }

    const [, user, repo, , type, path] = match
    return { user, repo, type, path }
}

export function getRelativeNextPath(nextPath: string | null | undefined, location: Location): string | null {
    if (!nextPath || typeof nextPath !== 'string') {
        return null
    }
    let decoded: string
    try {
        decoded = decodeURIComponent(nextPath)
    } catch {
        decoded = nextPath
    }

    // Protocol-relative URLs (e.g., //evil.com/test) are not allowed
    if (decoded.startsWith('//')) {
        return null
    }

    // Root-relative path — resolve against the current origin and verify it doesn't escape.
    // Browsers normalize backslashes in special-scheme URLs per WHATWG, so a raw startsWith('/')
    // check would accept '/\\evil.com/path', which the browser then loads as '//evil.com/path'.
    if (decoded.startsWith('/')) {
        try {
            const url = new URL(decoded, location.origin)
            if (url.origin !== location.origin) {
                return null
            }
            return url.pathname + url.search + url.hash
        } catch {
            return null
        }
    }

    // Try to parse as a full URL
    try {
        const url = new URL(decoded)
        if ((url.protocol === 'http:' || url.protocol === 'https:') && url.origin === location.origin) {
            return url.pathname + url.search + url.hash
        }
        return null
    } catch {
        return null
    }
}
