import { detect } from 'detect-browser'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig, PluginLogEntrySource, PluginLogEntryType, PluginMethods } from '../../../types'
import { PluginInstance } from '../lazy'

export type UserAgentPluginConfiguration = {
    enable: string // unused
    enableSegmentAnalyticsJs?: string
    overrideUserAgentDetails?: string
    debugMode?: string
}

export class UserAgentPlugin implements PluginInstance {
    initialize = async () => {}
    failInitialization = async () => {}
    clearRetryTimeoutIfExists = async () => {}
    getTeardown = () => {
        return Promise.resolve(null)
    }
    setupPluginIfNeeded = () => {
        return Promise.resolve(true)
    }
    usedImports: Set<string> | undefined
    methods: PluginMethods

    hub: Hub
    config: PluginConfig

    enableSegmentAnalyticsJs: boolean
    overrideUserAgentDetails: boolean
    debugMode: boolean

    constructor(hub: Hub, pluginConfig: PluginConfig) {
        this.hub = hub
        this.config = pluginConfig
        this.usedImports = new Set()

        const config = pluginConfig.config as UserAgentPluginConfiguration

        this.enableSegmentAnalyticsJs = config.enableSegmentAnalyticsJs === 'true'
        this.overrideUserAgentDetails = config.overrideUserAgentDetails === 'true'
        this.debugMode = config.debugMode === 'true'

        this.methods = {
            processEvent: (event: PluginEvent) => {
                return this.addBrowserDetails(event)
            },
        }
    }

    public getPluginMethod<T extends keyof PluginMethods>(method_name: T): Promise<PluginMethods[T] | null> {
        return Promise.resolve(this.methods[method_name] as PluginMethods[T])
    }

    async addBrowserDetails(event: PluginEvent): Promise<PluginEvent> {
        if (!event.properties) {
            event.properties = {}
        }
        const availableKeysOfEvent = Object.keys(event.properties)

        let userAgent = ''

        if (this.enableSegmentAnalyticsJs) {
            // If the segment integration is enabled and the segment_userAgent is missing, we skip the processing of the event
            if (!availableKeysOfEvent.includes('segment_userAgent')) {
                if (this.debugMode) {
                    await this.createLogEntry(
                        `UserAgentPlugin.processEvent(): Event is missing segment_userAgent`,
                        PluginLogEntryType.Warn
                    )
                }

                return event
            }
            userAgent = `${event.properties.segment_userAgent}`
        } else {
            // If the magical property name $useragent is missing, we skip the processing of the event
            const hasUserAgentKey =
                availableKeysOfEvent.includes('$user-agent') ||
                availableKeysOfEvent.includes('$useragent') ||
                availableKeysOfEvent.includes('$user_agent')
            if (!hasUserAgentKey) {
                if (this.debugMode) {
                    await this.createLogEntry(
                        `UserAgentPlugin.processEvent(): Event is missing $useragent or $user-agent`,
                        PluginLogEntryType.Warn
                    )
                }

                return event
            }

            // Extract user agent from event properties
            if (event.properties.$useragent) {
                userAgent = event.properties.$useragent
            } else if (event.properties['$user-agent']) {
                userAgent = event.properties['$user-agent']
            } else if (event.properties.$user_agent) {
                userAgent = event.properties.$user_agent
            }

            // Remove the unnecessary $useragent or $user-agent user property
            delete event.properties.$useragent
            delete event.properties['$user-agent']
            delete event.properties.$user_agent
        }

        if (!userAgent || userAgent === '') {
            if (this.debugMode) {
                await this.createLogEntry(
                    `UserAgentPlugin.processEvent(): $useragent is empty`,
                    PluginLogEntryType.Warn
                )
            }

            return event
        }

        const agentInfo = detect(userAgent)
        const device = detectDevice(userAgent)
        const deviceType = detectDeviceType(userAgent)

        const eventProperties = Object.keys(event.properties)
        const hasBrowserProperties = eventProperties.some((value: string) =>
            ['$browser', '$browser_version', '$os', '$device', '$device_type'].includes(value)
        )

        if (!this.overrideUserAgentDetails && hasBrowserProperties) {
            if (this.debugMode) {
                await this.createLogEntry(
                    `UserAgentPlugin.processEvent(): The event has $browser, $browser_version, $os, $device, or $device_type but the option 'overrideUserAgentDetails' is not enabled.`,
                    PluginLogEntryType.Warn
                )
            }

            return event
        }

        event.properties['$device'] = device
        event.properties['$device_type'] = deviceType

        if (agentInfo) {
            event.properties['$browser'] = agentInfo.name
            event.properties['$browser_version'] = agentInfo.version
            event.properties['$os'] = agentInfo.os
            // Custom property
            event.properties['$browser_type'] = agentInfo.type
        }

        return event
    }

    public async createLogEntry(message: string, logType = PluginLogEntryType.Info): Promise<void> {
        // TODO - this will be identical across all plugins, so figure out a better place to put it.
        await this.hub.db.queuePluginLogEntry({
            message,
            pluginConfig: this.config,
            source: PluginLogEntrySource.System,
            type: logType,
            instanceId: this.hub.instanceId,
        })
    }
}

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

export const USER_AGENT_CONFIG_SCHEMA = [
    {
        markdown:
            "User Agent plugin allows you to populate events with the $browser, $browser_version for PostHog Clients that don't  typically populate these properties",
    },
    {
        key: 'overrideUserAgentDetails',
        name: 'Can override existing browser related properties of event?',
        type: 'string' as const,
        hint: 'If the ingested event already have $browser $browser_version properties in combination with $useragent the $browser, $browser_version properties will be re-populated with the value of $useragent',
        default: 'false',
        required: false,
    },
    {
        key: 'enableSegmentAnalyticsJs',
        name: 'Automatically read segment_userAgent property, automatically sent by Segment via analytics.js?',
        type: 'choice' as const,
        hint: "Segment's analytics.js library automatically sends a useragent property that Posthog sees as segment_userAgent. Enabling this causes this plugin to parse that property",
        choices: ['false', 'true'],
        default: 'false',
        required: false,
    },
    {
        key: 'debugMode',
        type: 'choice' as const,
        hint: 'Enable debug mode to log when the plugin is unable to extract values from the user agent',
        choices: ['false', 'true'],
        default: 'false',
        required: false,
    },
]
