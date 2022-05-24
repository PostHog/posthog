import { PluginCapabilities, PluginConfigVMResponse, VMMethods } from '../../types'
import { PluginServerCapabilities } from './../../types'

export function getVMPluginCapabilities(vm: PluginConfigVMResponse): PluginCapabilities {
    const capabilities: Required<PluginCapabilities> = { scheduled_tasks: [], jobs: [], methods: [] }

    const tasks = vm?.tasks
    const methods = vm?.methods

    if (methods) {
        for (const [key, value] of Object.entries(methods)) {
            if (value as VMMethods[keyof VMMethods] | undefined) {
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
    if (serverCapability === 'ingestion') {
        return pluginCapabilities.methods?.includes('processEvent')
    }
    if (serverCapability === 'pluginScheduledTasks') {
        return (pluginCapabilities.scheduled_tasks || []).length > 0
    }
    if (serverCapability === 'processJobs') {
        return (pluginCapabilities.jobs || []).length > 0
    }
    if (serverCapability === 'processAsyncHandlers') {
        return pluginCapabilities.methods?.some((method) =>
            ['onAction', 'onSnapshot', 'onEvent', 'exportEvents'].includes(method)
        )
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
