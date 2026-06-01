import { detect } from 'detect-browser'

import { PluginEvent } from '~/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

export type UserAgentMeta = LegacyTransformationPluginMeta & {
    config: {
        enable: string
        enableSegmentAnalyticsJs?: string
        overrideUserAgentDetails?: string
        debugMode?: string
    }
    global: {
        enabledPlugin: boolean
        enableSegmentAnalyticsJs: boolean
        overrideUserAgentDetails: boolean
        debugMode: boolean
    }
}

/**
 * Setup of the plugin
 * @param param0 the metadata of the plugin
 */
export function setupPlugin({ config, global }: UserAgentMeta) {
    try {
        global.enableSegmentAnalyticsJs = config.enableSegmentAnalyticsJs === 'true'
        global.overrideUserAgentDetails = config.overrideUserAgentDetails === 'true'
        global.debugMode = config.debugMode === 'true'
    } catch {
        throw new Error('Failed to read the configuration')
    }
}

/**
 * Process the event
 */
export function processEvent(event: PluginEvent, { global, logger }: UserAgentMeta) {
    const properties = event.properties || {}
    const availableKeysOfEvent = Object.keys(properties)

    let userAgent = ''

    if (global.enableSegmentAnalyticsJs) {
        // If the segment integration is enabled and the segment_userAgent is missing, we skip the processing of the event
        const hasSegmentUserAgentKey = availableKeysOfEvent.includes('segment_userAgent')
        if (!hasSegmentUserAgentKey) {
            if (global.debugMode) {
                logger.warn(`UserAgentPlugin.processEvent(): Event is missing segment_userAgent`)
            }

            return event
        }

        // Extract user agent from event properties
        userAgent = `${properties.segment_userAgent ?? ''}`
    } else {
        // If the magical property name $useragent is missing, we skip the processing of the event
        const hasUserAgentKey =
            availableKeysOfEvent.includes('$user-agent') ||
            availableKeysOfEvent.includes('$useragent') ||
            availableKeysOfEvent.includes('$user_agent')
        if (!hasUserAgentKey) {
            if (global.debugMode) {
                logger.warn(`UserAgentPlugin.processEvent(): Event is missing $useragent or $user-agent`)
            }

            return event
        }

        // Extract user agent from event properties
        if (properties.$useragent) {
            userAgent = properties.$useragent
        } else if (properties['$user-agent']) {
            userAgent = properties['$user-agent']
        } else if (properties.$user_agent) {
            userAgent = properties.$user_agent
        }

        // Remove the unnecessary $useragent or $user-agent user property
        delete properties.$useragent
        delete properties['$user-agent']
        delete properties.$user_agent
    }

    if (!userAgent || userAgent === '') {
        if (global.debugMode) {
            logger.warn(`UserAgentPlugin.processEvent(): $useragent is empty`)
        }

        return event
    }

    const agentInfo = detect(userAgent)
    const browserFork = detectBrowserFork(userAgent)
    const device = detectDevice(userAgent)
    const deviceType = detectDeviceType(userAgent)

    const eventProperties = Object.keys(properties)
    const hasBrowserProperties = eventProperties.some((value: string) =>
        ['$browser', '$browser_version', '$os', '$device', '$device_type'].includes(value)
    )

    if (!global.overrideUserAgentDetails && hasBrowserProperties) {
        if (global.debugMode) {
            logger.warn(
                `UserAgentPlugin.processEvent(): The event has $browser, $browser_version, $os, $device, or $device_type but the option 'overrideUserAgentDetails' is not enabled.`
            )
        }

        return event
    }

    // The special Posthog property names are retrieved from:
    // https://github.com/PostHog/posthog/blob/master/frontend/src/lib/components/PropertyKeyInfo.tsx
    properties['$device'] = device
    properties['$device_type'] = deviceType

    if (agentInfo) {
        properties['$browser'] = agentInfo.name
        properties['$browser_version'] = agentInfo.version
        properties['$os'] = agentInfo.os
        // Custom property
        properties['$browser_type'] = agentInfo.type
    }

    // Override $browser for Chromium / Firefox forks that detect-browser buckets
    // as Chrome / Firefox / Safari. $os and $browser_type still come from
    // detect-browser above.
    if (browserFork) {
        properties['$browser'] = browserFork.name
        properties['$browser_version'] = browserFork.version
    }

    event.properties = properties

    return event
}

// Chromium and Firefox forks that stamp themselves into the UA string. We detect
// them here because detect-browser buckets them as Chrome / Firefox / Safari.
// Ported from posthog-js so server-populated $browser matches what the SDK sets
// client-side:
// https://github.com/PostHog/posthog-js/blob/master/packages/core/src/utils/user-agent-utils.ts
//
// Desktop / Android Brave is intentionally invisible in the UA (posthog-js detects
// it via navigator.brave, which isn't available server-side), so it still falls
// through to Chrome here. Only Brave on iOS carries a `Brave/` marker.
//
// Order mirrors posthog-js: each fork's marker also contains Chrome/, Firefox/ or
// a Safari token, so the fork must be matched before the generic browser would be.
const BROWSER_FORKS: { name: string; marker: RegExp; versionRegex: RegExp }[] = [
    { name: 'Vivaldi', marker: /Vivaldi\//, versionRegex: /Vivaldi\/(\d+(?:\.\d+)?)/ },
    { name: 'Yandex', marker: /YaBrowser\//, versionRegex: /YaBrowser\/(\d+(?:\.\d+)?)/ },
    { name: 'Whale', marker: /Whale\//, versionRegex: /Whale\/(\d+(?:\.\d+)?)/ },
    { name: 'DuckDuckGo', marker: /DuckDuckGo\/|Ddg\//, versionRegex: /(?:DuckDuckGo|Ddg)\/(\d+(?:\.\d+)?)/ },
    { name: 'Brave', marker: /Brave\//, versionRegex: /Brave\/(\d+(?:\.\d+)?)/ },
    { name: 'Pale Moon', marker: /PaleMoon\//, versionRegex: /PaleMoon\/(\d+(?:\.\d+)?)/ },
    { name: 'Waterfox', marker: /Waterfox\//, versionRegex: /Waterfox\/(\d+(?:\.\d+)?)/ },
]

// Returns the fork name and its parsed version, or null when no fork marker matches.
// version is null when the marker is present but carries no numeric version (e.g.
// Waterfox's `Waterfox/G6.0.13` classic-series marker) — honest rather than faked.
function detectBrowserFork(userAgent: string): { name: string; version: string | null } | null {
    for (const { name, marker, versionRegex } of BROWSER_FORKS) {
        if (marker.test(userAgent)) {
            const match = userAgent.match(versionRegex)
            return { name, version: match ? match[1] : null }
        }
    }
    return null
}

// detectDevice and detectDeviceType from https://github.com/PostHog/posthog-js/blob/9abedce5ac877caeb09205c4b693988fc09a63ca/src/utils.js#L808-L837
function detectDevice(userAgent: string) {
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
    } else {
        return ''
    }
}

function detectDeviceType(userAgent: string) {
    const device = detectDevice(userAgent)
    if (device === 'iPad' || device === 'Android Tablet') {
        return 'Tablet'
    } else if (device) {
        return 'Mobile'
    } else {
        return 'Desktop'
    }
}
