import { PluginCapabilities, PluginMethods } from '../../types'
import { logger } from '../../utils/logger'
import { PluginServerCapabilities } from './../../types'

const PROCESS_EVENT_CAPABILITIES = new Set<keyof PluginServerCapabilities>(['ingestionV2', 'ingestionV2Combined'])

export function getVMPluginCapabilities(methods: PluginMethods): PluginCapabilities {
    const capabilities: Required<PluginCapabilities> = { methods: [] }

    if (methods) {
        for (const [key, value] of Object.entries(methods)) {
            if (value as PluginMethods[keyof PluginMethods] | undefined) {
                capabilities.methods.push(key)
            }
        }
    }

    return capabilities
}

function shouldSetupPlugin(serverCapability: keyof PluginServerCapabilities, pluginCapabilities: PluginCapabilities) {
    logger.info('shouldSetupPlugin', serverCapability, pluginCapabilities)
    if (PROCESS_EVENT_CAPABILITIES.has(serverCapability)) {
        return pluginCapabilities.methods?.includes('processEvent')
    }
    if (serverCapability === 'cdpLegacyOnEvent') {
        return pluginCapabilities.methods?.some((method) => ['onEvent', 'composeWebhook'].includes(method))
    }

    return false
}

export function shouldSetupPluginInServer(
    serverCapabilities: PluginServerCapabilities,
    pluginCapabilities: PluginCapabilities
): boolean {
    // return true if the plugin has any capability that matches an enabled server capability
    for (const [serverCapability, enabled] of Object.entries(serverCapabilities)) {
        if (enabled && shouldSetupPlugin(serverCapability as keyof PluginServerCapabilities, pluginCapabilities)) {
            return true
        }
    }

    return false
}
