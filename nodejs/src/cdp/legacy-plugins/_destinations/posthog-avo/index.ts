import { randomUUID } from 'crypto'

import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { LegacyDestinationPluginMeta } from '../../types'

type AvoPluginMeta = LegacyDestinationPluginMeta & {
    global: {
        defaultHeaders: Record<string, string>
        excludeEvents: Set<string>
        includeEvents: Set<string>
        excludeProperties: Set<string>
        includeProperties: Set<string>
    }
    config: {
        appName: string
        avoApiKey: string
        environment: string
        excludeEvents: string
        includeEvents: string
        excludeProperties: string
        includeProperties: string
    }
}
export const setupPlugin = ({ config, global }: AvoPluginMeta): Promise<void> => {
    global.defaultHeaders = {
        env: config.environment,
        'api-key': config.avoApiKey,
        'content-type': 'application/json',
        accept: 'application/json',
    }

    global.excludeEvents = new Set(
        config.excludeEvents ? config.excludeEvents.split(',').map((event) => event.trim()) : null
    )
    global.includeEvents = new Set(
        config.includeEvents ? config.includeEvents.split(',').map((event) => event.trim()) : null
    )
    global.excludeProperties = new Set(
        config.excludeProperties ? config.excludeProperties.split(',').map((event) => event.trim()) : null
    )
    global.includeProperties = new Set(
        config.includeProperties ? config.includeProperties.split(',').map((event) => event.trim()) : null
    )
    return Promise.resolve()
}

export const onEvent = async (
    event: ProcessedPluginEvent,
    { config, global, fetch }: LegacyDestinationPluginMeta
): Promise<void> => {
    const isIncluded = global.includeEvents.length > 0 ? global.includeEvents.has(event.event) : true
    const isExcluded = global.excludeEvents.has(event.event)

    if (event.event.startsWith('$') || isExcluded || !isIncluded) {
        return
    }

    const sessionId = randomUUID()
    const now = new Date().toISOString()

    const avoEvent = {
        apiKey: config.avoApiKey,
        env: config.environment,
        appName: config.appName,
        sessionId: sessionId,
        createdAt: now,
        avoFunction: false,
        eventId: null,
        eventHash: null,
        appVersion: '1.0.0',
        libVersion: '1.0.0',
        libPlatform: 'node',
        trackingId: '',
        samplingRate: 1,
        type: 'event',
        eventName: event.event,
        messageId: event.uuid,
        eventProperties: event.properties
            ? convertPosthogPropsToAvoProps(event.properties, global.excludeProperties, global.includeProperties)
            : [],
    }

    await fetch('https://api.avo.app/inspector/posthog/v1/track', {
        method: 'POST',
        headers: global.defaultHeaders,
        body: JSON.stringify([avoEvent]),
    })
}

const convertPosthogPropsToAvoProps = (
    properties: Record<string, any>,
    excludeProperties: Set<string>,
    includeProperties: Set<string>
): Record<string, string>[] => {
    const avoProps = []

    for (const [propertyName, propertyValue] of Object.entries(properties)) {
        const isIncluded = includeProperties.size > 0 ? includeProperties.has(propertyName) : true
        const isExcluded = excludeProperties.has(propertyName)

        if (propertyName.startsWith('$') || isExcluded || !isIncluded) {
            continue
        }

        avoProps.push({ propertyName, propertyType: getPropValueType(propertyValue) })
    }
    return avoProps
}

// Compatible with the Avo Rudderstack integration
const getPropValueType = (propValue: any): string => {
    const propType = typeof propValue
    if (propValue == null) {
        return 'null'
    } else if (propType === 'string') {
        return 'string'
    } else if (propType === 'number' || propType === 'bigint') {
        if ((propValue + '').indexOf('.') >= 0) {
            return 'float'
        } else {
            return 'int'
        }
    } else if (propType === 'boolean') {
        return 'boolean'
    } else if (propType === 'object') {
        if (Array.isArray(propValue)) {
            return 'list'
        } else {
            return 'object'
        }
    } else {
        return propType
    }
}
