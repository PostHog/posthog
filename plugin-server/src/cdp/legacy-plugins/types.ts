import { PluginEvent, ProcessedPluginEvent, StorageExtension } from '@posthog/plugin-scaffold'

import { FetchOptions, FetchResponse } from '../../utils/request'
import { HogFunctionTemplate } from '../types'

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
    fetch: (url: string, fetchParams: FetchOptions) => Promise<FetchResponse>
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
