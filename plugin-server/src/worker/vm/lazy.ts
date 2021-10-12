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
    initialize?: (hub: Hub, pluginConfig: PluginConfig, indexJs: string, logInfo: string) => Promise<void>
    failInitialization?: () => void
    resolveInternalVm!: Promise<PluginConfigVMResponse | null>
    totalInitAttemptsCounter: number
    initRetryTimeout: NodeJS.Timeout | null

    constructor() {
        this.totalInitAttemptsCounter = 0
        this.initRetryTimeout = null
        this.initVm()
    }

    public async getExportEvents(): Promise<PluginConfigVMResponse['methods']['exportEvents'] | null> {
        return (await this.resolveInternalVm)?.methods.exportEvents || null
    }

    public async getOnEvent(): Promise<PluginConfigVMResponse['methods']['onEvent'] | null> {
        return (await this.resolveInternalVm)?.methods.onEvent || null
    }

    public async getOnSnapshot(): Promise<PluginConfigVMResponse['methods']['onSnapshot'] | null> {
        return (await this.resolveInternalVm)?.methods.onSnapshot || null
    }

    public async getProcessEvent(): Promise<PluginConfigVMResponse['methods']['processEvent'] | null> {
        return (await this.resolveInternalVm)?.methods.processEvent || null
    }

    public async getTeardownPlugin(): Promise<PluginConfigVMResponse['methods']['teardownPlugin'] | null> {
        return (await this.resolveInternalVm)?.methods.teardownPlugin || null
    }

    public async getTask(name: string, type: PluginTaskType): Promise<PluginTask | null> {
        return (await this.resolveInternalVm)?.tasks?.[type]?.[name] || null
    }

    public async getTasks(type: PluginTaskType): Promise<Record<string, PluginTask>> {
        return (await this.resolveInternalVm)?.tasks?.[type] || {}
    }

    public clearRetryTimeoutIfExists(): void {
        if (this.initRetryTimeout) {
            clearTimeout(this.initRetryTimeout)
        }
    }

    private initVm() {
        this.totalInitAttemptsCounter++
        this.resolveInternalVm = new Promise((resolve) => {
            this.initialize = async (hub: Hub, pluginConfig: PluginConfig, indexJs: string, logInfo = '') => {
                const createLogEntry = async (message: string, logType = PluginLogEntryType.Info): Promise<void> => {
                    await hub.db.queuePluginLogEntry({
                        pluginConfig,
                        message,
                        source: PluginLogEntrySource.System,
                        type: logType,
                        instanceId: hub.instanceId,
                    })
                }
                try {
                    const vm = await createPluginConfigVM(hub, pluginConfig, indexJs)
                    await createLogEntry(`Plugin loaded (instance ID ${hub.instanceId}).`)
                    status.info('🔌', `Loaded ${logInfo}`)
                    void clearError(hub, pluginConfig)
                    await this.inferPluginCapabilities(hub, pluginConfig, vm)
                    resolve(vm)
                } catch (error) {
                    status.warn('⚠️', error.message)
                    await createLogEntry(error.message, PluginLogEntryType.Error)
                    void processError(hub, pluginConfig, error)
                    if (this.totalInitAttemptsCounter < MAX_SETUP_RETRIES) {
                        const nextRetryMs =
                            INITIALIZATION_RETRY_MULTIPLIER ** (this.totalInitAttemptsCounter - 1) *
                            INITIALIZATION_RETRY_BASE_MS
                        const nextRetrySeconds = `${nextRetryMs / 1000} s`
                        status.warn('⚠️', `Failed to load ${logInfo}. Retrying in ${nextRetrySeconds}.`)
                        await createLogEntry(
                            `Plugin failed to load (instance ID ${hub.instanceId}). Retrying in ${nextRetrySeconds}.`,
                            PluginLogEntryType.Error
                        )
                        this.initRetryTimeout = setTimeout(() => {
                            this.initVm()
                            void this.initialize?.(hub, pluginConfig, indexJs, logInfo)
                        }, nextRetryMs)
                        resolve(null)
                    } else {
                        const failureContextMessage = `Disabling it due to too many retries – tried to load it ${
                            this.totalInitAttemptsCounter
                        } time${this.totalInitAttemptsCounter > 1 ? 's' : ''} before giving up.`
                        status.warn('⚠️', `Failed to load ${logInfo}. ${failureContextMessage}`)
                        await createLogEntry(
                            `Plugin failed to load (instance ID ${hub.instanceId}). ${failureContextMessage}`,
                            PluginLogEntryType.Error
                        )
                        void disablePlugin(hub, pluginConfig.id)
                        resolve(null)
                    }
                }
            }
            this.failInitialization = () => {
                resolve(null)
            }
        })
    }

    private async inferPluginCapabilities(
        hub: Hub,
        pluginConfig: PluginConfig,
        vm: PluginConfigVMResponse
    ): Promise<void> {
        if (!pluginConfig.plugin) {
            throw new Error(`'PluginConfig missing plugin: ${pluginConfig}`)
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

        const prevCapabilities = pluginConfig.plugin.capabilities
        if (!equal(prevCapabilities, capabilities)) {
            await setPluginCapabilities(hub, pluginConfig, capabilities)
            pluginConfig.plugin.capabilities = capabilities
        }
    }
}
