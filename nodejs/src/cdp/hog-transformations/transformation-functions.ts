import { detect } from 'detect-browser'

import { GeoIp } from '~/common/utils/geoip'

import { KNOWN_BOT_IP_LIST, KNOWN_BOT_UA_LIST } from './bots/bots'

const MAX_DEPTH = 3

function cleanNullValuesInternal(value: unknown, depth: number): unknown {
    if (depth > MAX_DEPTH) {
        return value
    }

    if (value === null) {
        return null
    }

    // Handles arrays
    if (Array.isArray(value)) {
        return value.map((item) => cleanNullValuesInternal(item, depth + 1)).filter((item) => item !== null)
    }

    // Handle objects
    if (typeof value === 'object' && value !== null) {
        const result: Record<string, any> = {}
        for (const [key, val] of Object.entries(value)) {
            const cleaned = cleanNullValuesInternal(val, depth + 1)
            if (cleaned !== null) {
                result[key] = cleaned
            }
        }
        return result
    }

    return value
}

export function cleanNullValues(value: unknown): unknown {
    return cleanNullValuesInternal(value, 1)
}

export const isKnownBotUserAgent = (value: unknown): boolean => {
    if (typeof value !== 'string') {
        return false
    }

    const userAgent = (value as string).toLowerCase()
    return KNOWN_BOT_UA_LIST.some((bot) => userAgent.includes(bot))
}

export const isKnownBotIp = (ip: unknown): boolean => {
    if (typeof ip !== 'string') {
        return false
    }

    const ipString = ip as string
    return KNOWN_BOT_IP_LIST.includes(ipString)
}

// Device detection regexes, ported from posthog-js.
const detectDevice = (userAgent: string): string => {
    if (/Windows Phone/i.test(userAgent) || /WPDesktop/.test(userAgent)) {
        return 'Windows Phone'
    } else if (/iPad/.test(userAgent)) {
        return 'iPad'
    } else if (/iPod/.test(userAgent)) {
        return 'iPod Touch'
    } else if (/iPhone/.test(userAgent)) {
        return 'iPhone'
    } else if (/(BlackBerry|PlayBook|BB10)/i.test(userAgent)) {
        return 'BlackBerry'
    } else if (/Android/.test(userAgent) && !/Mobile/.test(userAgent)) {
        return 'Android Tablet'
    } else if (/Android/.test(userAgent)) {
        return 'Android'
    }
    return ''
}

const detectDeviceType = (userAgent: string): string => {
    const device = detectDevice(userAgent)
    if (device === 'iPad' || device === 'Android Tablet') {
        return 'Tablet'
    } else if (device) {
        return 'Mobile'
    }
    return 'Desktop'
}

// detect-browser's chrome patterns backtrack quadratically on repeated `Chrom` tokens, and a host
// function is a single VM operation, so the hog timeout cannot interrupt one. Real user agents run a
// few hundred bytes, so bound the input tightly: the cost is quadratic in length, and at 1024 even
// the worst crafted value parses in well under a millisecond, rather than let it stall the worker.
export const MAX_USER_AGENT_LENGTH = 1024

export const parseUserAgent = (
    value: unknown
): {
    browser: string | null
    browserVersion: string | null
    os: string | null
    browserType: string | null
    device: string
    deviceType: string
} | null => {
    if (typeof value !== 'string' || value === '' || value.length > MAX_USER_AGENT_LENGTH) {
        return null
    }

    const agentInfo = detect(value)
    return {
        browser: agentInfo ? agentInfo.name : null,
        browserVersion: agentInfo ? agentInfo.version : null,
        os: agentInfo && 'os' in agentInfo ? agentInfo.os : null,
        browserType: agentInfo ? agentInfo.type : null,
        device: detectDevice(value),
        deviceType: detectDeviceType(value),
    }
}

// Internal properties used in event processing are left nested.
const FLATTEN_PROPERTY_DENYLIST = [
    '$elements',
    '$elements_chain',
    '$groups',
    '$active_feature_flags',
    '$heatmap_data',
    '$web_vitals_data',
]

// Real separators join keys and run a few characters. Cap the configured one so a huge value
// cannot be copied into every flattened key and blow up memory and CPU.
const MAX_SEPARATOR_LENGTH = 100
// Backstop on the number of flattened keys, so one pathological event cannot generate an unbounded
// number of properties. Well above any real event; capture already bounds the event size.
const MAX_FLATTENED_KEYS = 100000
// Backstop on the total bytes of generated keys. A long property name above many leaves would
// otherwise copy that prefix into every key, so a small payload could produce megabytes of keys.
const MAX_FLATTENED_KEY_BYTES = 5_000_000

// Flattening runs as a host function rather than in hog, because the hog VM re-costs a local on
// every read, which makes an in-language recursive flatten quadratic in the property count and can
// exhaust the transformation time budget. This accumulates in place, so it is linear.
function flattenPropertiesInternal(
    props: Record<string, any>,
    sep: string,
    nestedChain: string[],
    budget: { keys: number; bytes: number }
): Record<string, any> {
    const newProps: Record<string, any> = {}
    for (const [key, value] of Object.entries(props)) {
        if (budget.keys <= 0 || budget.bytes <= 0) {
            break
        }
        if (FLATTEN_PROPERTY_DENYLIST.includes(key)) {
            // Leave internal properties nested.
        } else if (key === '$set' || key === '$set_once' || key === '$group_set') {
            // A flattened key that collides with an existing one wins, matching the legacy plugin:
            // for `{$set: {a__b: 1, a: {b: 2}}}` the flattened `a__b: 2` replaces the literal `a__b: 1`.
            newProps[key] = { ...(props[key] as object), ...flattenPropertiesInternal(props[key], sep, [], budget) }
        } else if (
            Array.isArray(value) ||
            (value !== null && typeof value === 'object' && Object.keys(value).length > 0)
        ) {
            Object.assign(newProps, flattenPropertiesInternal(props[key], sep, [...nestedChain, key], budget))
        } else if (nestedChain.length > 0) {
            const flatKey = nestedChain.join(sep) + sep + key
            newProps[flatKey] = value
            budget.keys -= 1
            budget.bytes -= flatKey.length
        }
    }
    return nestedChain.length > 0 ? newProps : { ...props, ...newProps }
}

export const flattenProperties = (properties: unknown, separator?: unknown): unknown => {
    if (properties === null || typeof properties !== 'object' || Array.isArray(properties)) {
        return properties
    }
    let sep = typeof separator === 'string' && separator.length > 0 ? separator : '__'
    if (sep.length > MAX_SEPARATOR_LENGTH) {
        sep = '__'
    }
    return flattenPropertiesInternal(properties as Record<string, any>, sep, [], {
        keys: MAX_FLATTENED_KEYS,
        bytes: MAX_FLATTENED_KEY_BYTES,
    })
}

export const getTransformationFunctions = (geoipLookup: GeoIp) => {
    return {
        geoipLookup: (val: unknown): any => {
            return typeof val === 'string' ? geoipLookup.city(val) : null
        },
        cleanNullValues,
        isKnownBotUserAgent,
        isKnownBotIp,
        parseUserAgent,
        flattenProperties,
        postHogCapture: () => {
            throw new Error('posthogCapture is not supported in transformations')
        },
    }
}
