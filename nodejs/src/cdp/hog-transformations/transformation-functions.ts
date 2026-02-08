import ipaddr from 'ipaddr.js'

import { GeoIp } from '~/utils/geoip'

import { KNOWN_BOT_CIDR_RANGES, KNOWN_BOT_IP_SET, KNOWN_BOT_UA_LIST } from './bots/bots'

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

    if (KNOWN_BOT_IP_SET.has(ip)) {
        return true
    }

    try {
        const parsed = ipaddr.parse(ip)
        return KNOWN_BOT_CIDR_RANGES.some((cidr) => {
            try {
                return parsed.match(cidr)
            } catch {
                return false
            }
        })
    } catch {
        return false
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
        postHogCapture: () => {
            throw new Error('posthogCapture is not supported in transformations')
        },
    }
}
