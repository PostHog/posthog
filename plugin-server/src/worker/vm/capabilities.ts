import { PluginCapabilities, PluginMethods, PluginTask, PluginTaskType } from '../../types'
import { PluginServerCapabilities } from './../../types'

const PROCESS_EVENT_CAPABILITIES = new Set(['ingestion', 'ingestionOverflow', 'ingestionHistorical'])

export function getVMPluginCapabilities(
    methods: PluginMethods,
    tasks: Record<PluginTaskType, Record<string, PluginTask>>
): PluginCapabilities {
    const capabilities: Required<PluginCapabilities> = { scheduled_tasks: [], jobs: [], methods: [] }

    if (methods) {
        for (const [key, value] of Object.entries(methods)) {
            if (value as PluginMethods[keyof PluginMethods] | undefined) {
                capabilities.methods.push(key)
            }
        }
    }

    if (tasks?.schedule) {
        for (const [key, value] of Object.entries(tasks.schedule)) {
            if (value) {
                capabilities.scheduled_tasks.push(key)
            }
        }
    }

    if (tasks?.job) {
        for (const [key, value] of Object.entries(tasks.job)) {
            if (value) {
                capabilities.jobs.push(key)
            }
        }
    }

    return capabilities
}

function shouldSetupPlugin(serverCapability: keyof PluginServerCapabilities, pluginCapabilities: PluginCapabilities) {
    if (PROCESS_EVENT_CAPABILITIES.has(serverCapability)) {
        return pluginCapabilities.methods?.includes('processEvent')
    }
    if (serverCapability === 'processAsyncOnEventHandlers') {
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
