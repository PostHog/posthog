import { PluginEvent, ProcessedPluginEvent, StorageExtension } from '@posthog/plugin-scaffold'

import { Response, trackedFetch } from '~/src/utils/fetch'

import { HogFunctionTemplate } from '../templates/types'

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
    storage: Pick<StorageExtension, 'get' | 'set'>
}

export type LegacyDestinationPlugin = {
    template: HogFunctionTemplate
    onEvent(event: ProcessedPluginEvent, meta: LegacyDestinationPluginMeta): Promise<void>
    setupPlugin?: (meta: LegacyDestinationPluginMeta) => Promise<void>
}

export type LegacyTransformationPlugin = {
    template: HogFunctionTemplate
    processEvent(event: PluginEvent, meta: LegacyTransformationPluginMeta): PluginEvent | undefined | null
    setupPlugin?: (meta: LegacyTransformationPluginMeta) => void
}
