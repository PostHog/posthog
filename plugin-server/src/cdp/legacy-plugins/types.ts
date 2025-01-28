import { PluginConfigSchema, ProcessedPluginEvent } from '@posthog/plugin-scaffold'

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
    fetch: (...args: Parameters<typeof trackedFetch>) => Promise<Response>
}

export type LegacyPlugin = {
    id: string
    metadata: {
        name: string
        config: PluginConfigSchema[]
    }
    onEvent(event: ProcessedPluginEvent, meta: LegacyPluginMeta): Promise<void>
    setupPlugin?: (meta: LegacyPluginMeta) => Promise<void>
}
