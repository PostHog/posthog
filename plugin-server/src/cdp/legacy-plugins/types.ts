import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { Response, trackedFetch } from '~/src/utils/fetch'

export type LegacyPluginLogger = {
    debug: (...args: any[]) => void
    warn: (...args: any[]) => void
    log: (...args: any[]) => void
    error: (...args: any[]) => void
}

export type LegacyPluginMeta = {
    config: Record<string, any>
    global: Record<string, any>
    logger: LegacyPluginLogger
}

export type LegacyTransformationPluginMeta = LegacyPluginMeta & {
    geoip: {
        locate: (ipAddress: string) => Record<string, any> | null
    }
}

export type LegacyDestinationPluginMeta = LegacyTransformationPluginMeta & {
    fetch: (...args: Parameters<typeof trackedFetch>) => Promise<Response>
}

export type LegacyDestinationPlugin = {
    id: string
    metadata: any
    onEvent(event: ProcessedPluginEvent, meta: LegacyDestinationPluginMeta): Promise<void>
    setupPlugin?: (meta: LegacyDestinationPluginMeta) => Promise<void>
}

export type LegacyTransformationPlugin = {
    id: string
    metadata: any
    processEvent(event: PluginEvent, meta: LegacyTransformationPluginMeta): PluginEvent | undefined | null
    setupPlugin?: (meta: LegacyTransformationPluginMeta) => void
}
