import { PluginCapabilities, PluginConfigVMResponse, VMMethods } from '../../types'

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
