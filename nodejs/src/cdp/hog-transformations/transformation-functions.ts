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
// function is a single VM operation, so the hog timeout cannot interrupt one. Real user agents are
// a few hundred bytes, so bound the input rather than let a crafted property value stall the worker.
export const MAX_USER_AGENT_LENGTH = 4096

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

export const getTransformationFunctions = (geoipLookup: GeoIp) => {
    return {
        geoipLookup: (val: unknown): any => {
            return typeof val === 'string' ? geoipLookup.city(val) : null
        },
        cleanNullValues,
        isKnownBotUserAgent,
        isKnownBotIp,
        parseUserAgent,
        postHogCapture: () => {
            throw new Error('posthogCapture is not supported in transformations')
        },
    }
}
