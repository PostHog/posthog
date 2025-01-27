import { Meta, PluginInput, ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { Response, trackedFetch } from '~/src/utils/fetch'

export type LegacyPluginLogger = {
    debug: (...args: any[]) => void
    warn: (...args: any[]) => void
    log: (...args: any[]) => void
    error: (...args: any[]) => void
}

export type LegacyPluginMeta<Input extends PluginInput> = Meta<Input> & {
    logger: LegacyPluginLogger
    fetch: (...args: Parameters<typeof trackedFetch>) => Promise<Response>
}

export type LegacyPlugin = {
    id: string
    onEvent<Input extends PluginInput>(event: ProcessedPluginEvent, meta: LegacyPluginMeta<Input>): Promise<void>
    setupPlugin?: (meta: LegacyPluginMeta<any>) => Promise<void>
}
