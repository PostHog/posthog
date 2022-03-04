import equal from 'fast-deep-equal'

import {
    Hub,
    PluginCapabilities,
    PluginConfig,
    PluginConfigVMResponse,
    PluginLogEntrySource,
    PluginLogEntryType,
    PluginTask,
    PluginTaskType,
    VMMethods,
} from '../../types'
import { clearError, processError } from '../../utils/db/error'
import { disablePlugin, setPluginCapabilities, setPluginMetrics } from '../../utils/db/sql'
import { status } from '../../utils/status'
import { createPluginConfigVM } from './vm'

const MAX_SETUP_RETRIES = 10
const INITIALIZATION_RETRY_MULTIPLIER = 2
const INITIALIZATION_RETRY_BASE_MS = 3000

export class LazyPluginVM {
    initialize?: (indexJs: string, logInfo: string) => Promise<void>
    failInitialization?: () => void
    resolveInternalVm!: Promise<PluginConfigVMResponse | null>
    totalInitAttemptsCounter: number
    initRetryTimeout: NodeJS.Timeout | null
    ready: boolean
    vmResponseVariable: string | null
    pluginConfig: PluginConfig
    hub: Hub

    constructor(hub: Hub, pluginConfig: PluginConfig) {
        this.totalInitAttemptsCounter = 0
        this.initRetryTimeout = null
        this.ready = false
        this.vmResponseVariable = null
        this.pluginConfig = pluginConfig
        this.hub = hub
        this.initVm()
    }

    public async getExportEvents(): Promise<PluginConfigVMResponse['methods']['exportEvents'] | null> {
        return await this.getVmMethod('exportEvents')
    }

    public async getOnEvent(): Promise<PluginConfigVMResponse['methods']['onEvent'] | null> {
        return await this.getVmMethod('onEvent')
    }

    public async getOnAction(): Promise<PluginConfigVMResponse['methods']['onAction'] | null> {
        return await this.getVmMethod('onAction')
    }

    public async getOnSnapshot(): Promise<PluginConfigVMResponse['methods']['onSnapshot'] | null> {
        return await this.getVmMethod('onSnapshot')
    }

    public async getProcessEvent(): Promise<PluginConfigVMResponse['methods']['processEvent'] | null> {
        return await this.getVmMethod('processEvent')
    }

    public async getHandleAlert(): Promise<PluginConfigVMResponse['methods']['handleAlert'] | null> {
        return await this.getVmMethod('handleAlert')
    }

    public async getTeardownPlugin(): Promise<PluginConfigVMResponse['methods']['teardownPlugin'] | null> {
        // if we never ran `setupPlugin`, there's no reason to run `teardownPlugin` - it's essentially "tore down" already
        if (!this.ready) {
            return null
        }
        return (await this.resolveInternalVm)?.methods['teardownPlugin'] || null
    }

    public async getTask(name: string, type: PluginTaskType): Promise<PluginTask | null> {
        const task = (await this.resolveInternalVm)?.tasks?.[type]?.[name] || null
        if (!this.ready && task) {
            await this.setupPluginIfNeeded()
        }
        return task
    }

    public async getTasks(type: PluginTaskType): Promise<Record<string, PluginTask>> {
        const tasks = (await this.resolveInternalVm)?.tasks?.[type] || null
        if (!this.ready && tasks && Object.values(tasks).length > 0) {
            await this.setupPluginIfNeeded()
        }
        return tasks || {}
    }

    private async getVmMethod<T extends keyof VMMethods>(method: T): Promise<VMMethods[T] | null> {
        const vmMethod = (await this.resolveInternalVm)?.methods[method] || null
        if (!this.ready && vmMethod) {
            await this.setupPluginIfNeeded()
        }

        return vmMethod
    }

    public clearRetryTimeoutIfExists(): void {
        if (this.initRetryTimeout) {
            clearTimeout(this.initRetryTimeout)
        }
    }

    private initVm() {
        this.totalInitAttemptsCounter++
        this.resolveInternalVm = new Promise((resolve) => {
            this.initialize = async (indexJs: string, logInfo = '') => {
                const createLogEntry = async (message: string, logType = PluginLogEntryType.Info): Promise<void> => {
                    await this.hub.db.queuePluginLogEntry({
                        message,
                        pluginConfig: this.pluginConfig,
                        source: PluginLogEntrySource.System,
                        type: logType,
                        instanceId: this.hub.instanceId,
                    })
                }
                try {
                    const vm = createPluginConfigVM(this.hub, this.pluginConfig, indexJs)
                    this.vmResponseVariable = vm.vmResponseVariable
                    const shouldSetupNow =
                        (!this.ready && // harmless check used to skip setup in tests
                            vm.tasks?.schedule &&
                            Object.values(vm.tasks?.schedule).length > 0) ||
                        (vm.tasks?.job && Object.values(vm.tasks?.job).length > 0)
                    if (shouldSetupNow) {
                        await vm.vm.run(`${this.vmResponseVariable}.methods.setupPlugin?.()`)
                        this.ready = true
                    }
                    await createLogEntry(`Plugin loaded (instance ID ${this.hub.instanceId}).`)
                    status.info('🔌', `Loaded ${logInfo}`)
                    void clearError(this.hub, this.pluginConfig)
                    await this.inferPluginCapabilities(vm)
                    resolve(vm)
                } catch (error) {
                    status.warn('⚠️', error.message)
                    await createLogEntry(error.message, PluginLogEntryType.Error)
                    void processError(this.hub, this.pluginConfig, error)
                    if (this.totalInitAttemptsCounter < MAX_SETUP_RETRIES) {
                        const nextRetryMs =
                            INITIALIZATION_RETRY_MULTIPLIER ** (this.totalInitAttemptsCounter - 1) *
                            INITIALIZATION_RETRY_BASE_MS
                        const nextRetrySeconds = `${nextRetryMs / 1000} s`
                        status.warn('⚠️', `Failed to load ${logInfo}. Retrying in ${nextRetrySeconds}.`)
                        await createLogEntry(
                            `Plugin failed to load (instance ID ${this.hub.instanceId}). Retrying in ${nextRetrySeconds}.`,
                            PluginLogEntryType.Error
                        )
                        this.initRetryTimeout = setTimeout(() => {
                            this.initVm()
                            void this.initialize?.(indexJs, logInfo)
                        }, nextRetryMs)
                        resolve(null)
                    } else {
                        const failureContextMessage = `Disabling it due to too many retries – tried to load it ${
                            this.totalInitAttemptsCounter
                        } time${this.totalInitAttemptsCounter > 1 ? 's' : ''} before giving up.`
                        status.warn('⚠️', `Failed to load ${logInfo}. ${failureContextMessage}`)
                        await createLogEntry(
                            `Plugin failed to load (instance ID ${this.hub.instanceId}). ${failureContextMessage}`,
                            PluginLogEntryType.Error
                        )
                        void disablePlugin(this.hub, this.pluginConfig.id)
                        resolve(null)
                    }
                }
            }
            this.failInitialization = () => {
                resolve(null)
            }
        })
    }

    public async setupPluginIfNeeded(): Promise<void> {
        if (this.ready) {
            return
        }
        await (await this.resolveInternalVm)?.vm.run(`${this.vmResponseVariable}.methods.setupPlugin?.()`)
        this.ready = true
    }

    private async inferPluginCapabilities(vm: PluginConfigVMResponse): Promise<void> {
        if (!this.pluginConfig.plugin) {
            throw new Error(`'PluginConfig missing plugin: ${this.pluginConfig}`)
        }

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

        const prevCapabilities = this.pluginConfig.plugin.capabilities
        if (!equal(prevCapabilities, capabilities)) {
            await setPluginCapabilities(this.hub, this.pluginConfig, capabilities)
            this.pluginConfig.plugin.capabilities = capabilities
        }
    }
}
