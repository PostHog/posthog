import equal from 'fast-deep-equal'
import { VM } from 'vm2'

import {
    Hub,
    PluginConfig,
    PluginConfigVMResponse,
    PluginLogEntrySource,
    PluginLogEntryType,
    PluginTask,
    PluginTaskType,
    VMMethods,
} from '../../../types'
import { clearError, processError } from '../../../utils/db/error'
import { disablePlugin, setPluginCapabilities } from '../../../utils/db/sql'
import { status } from '../../../utils/status'
import { pluginDigest } from '../../../utils/utils'
import { createPluginConfigVM } from '../vm'
import { getVMPluginCapabilities, shouldSetupPluginInServer } from './capabilities'
import { getNextRetryMs, VM_INIT_MAX_RETRIES } from './retries'

export class SetupPluginError extends Error {}

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
    lastError: Error | null

    constructor(hub: Hub, pluginConfig: PluginConfig) {
        this.totalInitAttemptsCounter = 0
        this.initRetryTimeout = null
        this.ready = false
        this.vmResponseVariable = null
        this.pluginConfig = pluginConfig
        this.hub = hub
        this.lastError = null
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
        return this.ready ? task : null
    }

    public async getScheduledTasks(): Promise<Record<string, PluginTask>> {
        let tasks = (await this.resolveInternalVm)?.tasks?.[PluginTaskType.Schedule] || null
        if (!this.ready && tasks && Object.values(tasks).length > 0) {
            const pluginReady = await this.setupPluginIfNeeded()
            if (!pluginReady) {
                tasks = null
                // KLUDGE: setupPlugin is retried, meaning methods may fail initially but work after a retry
                // Schedules on the other hand need to be loaded in advance, so retries cannot turn on scheduled tasks after the fact.
                await this.createLogEntry(
                    'Cannot load scheduled tasks because the plugin errored during setup.',
                    PluginLogEntryType.Error
                )
            }
        }
        return tasks || {}
    }

    private async getVmMethod<T extends keyof VMMethods>(method: T): Promise<VMMethods[T] | null> {
        const vmMethod = (await this.resolveInternalVm)?.methods[method] || null
        if (!this.ready && vmMethod) {
            await this.setupPluginIfNeeded()
        }
        return this.ready ? vmMethod : null
    }

    public clearRetryTimeoutIfExists(): void {
        if (this.initRetryTimeout) {
            clearTimeout(this.initRetryTimeout)
        }
    }

    private initVm() {
        this.resolveInternalVm = new Promise((resolve) => {
            this.initialize = async (indexJs: string, logInfo = '') => {
                try {
                    const vm = createPluginConfigVM(this.hub, this.pluginConfig, indexJs)
                    this.vmResponseVariable = vm.vmResponseVariable

                    if (!this.pluginConfig.plugin) {
                        throw new Error(`'PluginConfig missing plugin: ${this.pluginConfig}`)
                    }

                    await this.updatePluginCapabilitiesIfNeeded(vm)

                    const shouldSetupPlugin = shouldSetupPluginInServer(
                        this.hub.capabilities,
                        this.pluginConfig.plugin!.capabilities!
                    )

                    if (!shouldSetupPlugin) {
                        resolve(null)
                        return
                    }

                    const shouldSetupNow =
                        (!this.ready && // harmless check used to skip setup in tests
                            vm.tasks?.schedule &&
                            Object.values(vm.tasks?.schedule).length > 0) ||
                        (vm.tasks?.job && Object.values(vm.tasks?.job).length > 0)

                    if (shouldSetupNow) {
                        await this._setupPlugin(vm.vm)
                    }

                    await this.createLogEntry(`Plugin loaded (instance ID ${this.hub.instanceId}).`)
                    status.info('🔌', `Loaded ${logInfo}`)
                    resolve(vm)
                } catch (error) {
                    status.warn('⚠️', error.message)
                    if (!(error instanceof SetupPluginError)) {
                        await this.processVmSetupError(error)
                    }
                    resolve(null)
                }
            }
            this.failInitialization = () => {
                resolve(null)
            }
        })
    }

    public async setupPluginIfNeeded(): Promise<boolean> {
        // If we haven't yet kicked off setupPlugin, trigger it, else we're already retrying it
        if (!this.ready && this.totalInitAttemptsCounter === 0) {
            const vm = (await this.resolveInternalVm)?.vm
            try {
                await this._setupPlugin(vm)
            } catch {
                return false
            }
        }
        return this.ready
    }

    public async _setupPlugin(vm?: VM): Promise<void> {
        const plugin = this.pluginConfig.plugin
        const logInfo = plugin ? pluginDigest(plugin) : `pluginConfig with ID '${this.pluginConfig.id}'`

        if (++this.totalInitAttemptsCounter > VM_INIT_MAX_RETRIES) {
            const failureContextMessage = `Disabling it due to too many retries – tried to load it ${
                this.totalInitAttemptsCounter
            } time${this.totalInitAttemptsCounter > 1 ? 's' : ''} before giving up.`
            await this.processVmSetupError(this.lastError || new Error('unknown error'), failureContextMessage)
            throw new SetupPluginError(`setupPlugin failed for ${logInfo}. ${failureContextMessage}`)
        }

        try {
            await vm?.run(`${this.vmResponseVariable}.methods.setupPlugin?.()`)
            await this.vmReady(logInfo)
        } catch (error) {
            const nextRetryMs = getNextRetryMs(this.totalInitAttemptsCounter)
            status.warn('⚠️', `setupPlugin failed for ${logInfo}. Retrying in ${nextRetryMs / 1000}s.`)
            await this.createLogEntry(
                `setupPlugin failed (instance ID ${this.hub.instanceId}). Retrying in ${
                    nextRetryMs / 1000
                }s. Error:\n\n${error.message}`,
                PluginLogEntryType.Error
            )
            this.lastError = error
            this.retrySetupPlugin(vm, nextRetryMs)
        }
    }

    private async vmReady(logInfo: string): Promise<void> {
        this.ready = true
        await this.createLogEntry(`setupPlugin completed successfully (instance ID ${this.hub.instanceId}).`)
        status.info('🔌', `setupPlugin completed successfully for ${logInfo}`)
        this.lastError = null
        void clearError(this.hub, this.pluginConfig)
    }

    private retrySetupPlugin(vm: VM | undefined, nextRetryMs: number): void {
        this.clearRetryTimeoutIfExists()
        this.initRetryTimeout = setTimeout(async () => {
            await this._setupPlugin(vm)
        }, nextRetryMs)
    }

    private async createLogEntry(message: string, logType = PluginLogEntryType.Info): Promise<void> {
        await this.hub.db.queuePluginLogEntry({
            message,
            pluginConfig: this.pluginConfig,
            source: PluginLogEntrySource.System,
            type: logType,
            instanceId: this.hub.instanceId,
        })
    }

    private async processVmSetupError(error: Error, additionalContext?: string): Promise<void> {
        void processError(this.hub, this.pluginConfig, error)
        additionalContext = additionalContext ?? `Error: ${error.message}`
        await this.createLogEntry(
            `Plugin failed to load (instance ID ${this.hub.instanceId}). ${additionalContext}`,
            PluginLogEntryType.Error
        )
        void disablePlugin(this.hub, this.pluginConfig.id)
    }

    private async updatePluginCapabilitiesIfNeeded(vm: PluginConfigVMResponse): Promise<void> {
        const capabilities = getVMPluginCapabilities(vm)

        const prevCapabilities = this.pluginConfig.plugin!.capabilities
        if (!equal(prevCapabilities, capabilities)) {
            await setPluginCapabilities(this.hub, this.pluginConfig, capabilities)
            this.pluginConfig.plugin!.capabilities = capabilities
        }
    }
}
