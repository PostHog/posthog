import { ConsoleExtension } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig, PluginLogEntrySource, PluginLogEntryType } from '../../../types'
import { logger } from '../../../utils/logger'
import { pluginDigest } from '../../../utils/utils'

function consoleFormat(...args: unknown[]): string {
    return args
        .map((arg) => {
            const argString = String(arg)
            if (argString === '[object Object]' || Array.isArray(arg)) {
                return JSON.stringify(arg)
            }
            return argString
        })
        .join(' ')
}

export function createConsole(hub: Hub, pluginConfig: PluginConfig): ConsoleExtension {
    async function consolePersist(type: PluginLogEntryType, ...args: unknown[]): Promise<void> {
        logger.debug(
            '👉',
            `${type} in ${pluginDigest(pluginConfig.plugin || pluginConfig.plugin_id, pluginConfig.team_id)}:`,
            ...args
        )

        await hub.db.queuePluginLogEntry({
            pluginConfig,
            type,
            source: PluginLogEntrySource.Console,
            message: consoleFormat(...args),
            instanceId: hub.instanceId,
        })
    }

    return {
        debug: (...args) => consolePersist(PluginLogEntryType.Debug, ...args),
        log: (...args) => consolePersist(PluginLogEntryType.Log, ...args),
        info: (...args) => consolePersist(PluginLogEntryType.Info, ...args),
        warn: (...args) => consolePersist(PluginLogEntryType.Warn, ...args),
        error: (...args) => consolePersist(PluginLogEntryType.Error, ...args),
    }
}
