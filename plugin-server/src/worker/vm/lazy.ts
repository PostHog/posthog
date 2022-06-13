import { RetryError } from '@posthog/plugin-scaffold'
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
} from '../../types'
import { clearError, processError } from '../../utils/db/error'
import { disablePlugin, setPluginCapabilities } from '../../utils/db/sql'
import { status } from '../../utils/status'
import { pluginDigest } from '../../utils/utils'
import { getVMPluginCapabilities, shouldSetupPluginInServer } from '../vm/capabilities'
import { createPluginConfigVM } from './vm'

export const VM_INIT_MAX_RETRIES = 5
export const INITIALIZATION_RETRY_MULTIPLIER = 2
export const INITIALIZATION_RETRY_BASE_MS = 5000

export class SetupPluginError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'SetupPluginError'
    }
}

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
    inErroredState: boolean

    constructor(hub: Hub, pluginConfig: PluginConfig) {
        this.totalInitAttemptsCounter = 0
        this.initRetryTimeout = null
        this.ready = false
        this.vmResponseVariable = null
        this.pluginConfig = pluginConfig
        this.hub = hub
        this.inErroredState = false
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
        let task = (await this.resolveInternalVm)?.tasks?.[type]?.[name] || null
        if (!this.ready && task) {
            const pluginReady = await this.setupPluginIfNeeded()
            if (!pluginReady) {
                task = null
            }
        }
        return task
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
                    'Cannot load scheduled tasks because the app errored during setup.',
                    PluginLogEntryType.Error
                )
            }
        }
        return tasks || {}
    }

    private async getVmMethod<T extends keyof VMMethods>(method: T): Promise<VMMethods[T] | null> {
        let vmMethod = (await this.resolveInternalVm)?.methods[method] || null
        if (!this.ready && vmMethod) {
            const pluginReady = await this.setupPluginIfNeeded()
            if (!pluginReady) {
                vmMethod = null
            }
        }
        return vmMethod
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
                        this.ready = true
                    }
                    status.info('🔌', `Loaded ${logInfo}.`)
                    await this.createLogEntry(`Plugin loaded (instance ID ${this.hub.instanceId}).`)
                    resolve(vm)
                } catch (error) {
                    status.warn('⚠️', `Failed to load ${logInfo}. ${error}`)
                    if (!(error instanceof SetupPluginError)) {
                        await this.processFatalVmSetupError(error, true)
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
        if (this.inErroredState) {
            return false
        }

        if (!this.ready) {
            const vm = (await this.resolveInternalVm)?.vm
            try {
                await this._setupPlugin(vm)
            } catch (error) {
                status.warn('⚠️', error.message)
                return false
            }
        }
        return true
    }

    public async _setupPlugin(vm?: VM): Promise<void> {
        const logInfo = this.pluginConfig.plugin
            ? pluginDigest(this.pluginConfig.plugin)
            : `plugin config ID '${this.pluginConfig.id}'`
        this.totalInitAttemptsCounter++
        try {
            await vm?.run(`${this.vmResponseVariable}.methods.setupPlugin?.()`)
            this.ready = true
            status.info('🔌', `setupPlugin succeeded for ${logInfo}.`)
            await this.createLogEntry(`setupPlugin succeeded (instance ID ${this.hub.instanceId}).`)
            void clearError(this.hub, this.pluginConfig)
        } catch (error) {
            this.clearRetryTimeoutIfExists()
            if (error instanceof RetryError) {
                error._attempt = this.totalInitAttemptsCounter
                error._maxAttempts = VM_INIT_MAX_RETRIES
            }
            if (error instanceof RetryError && this.totalInitAttemptsCounter < VM_INIT_MAX_RETRIES) {
                const nextRetryMs =
                    INITIALIZATION_RETRY_MULTIPLIER ** (this.totalInitAttemptsCounter - 1) *
                    INITIALIZATION_RETRY_BASE_MS
                const nextRetrySeconds = `${nextRetryMs / 1000} s`
                status.warn('⚠️', `setupPlugin failed with ${error} for ${logInfo}. Retrying in ${nextRetrySeconds}...`)
                await this.createLogEntry(
                    `setupPlugin failed with ${error} (instance ID ${this.hub.instanceId}). Retrying in ${nextRetrySeconds}...`,
                    PluginLogEntryType.Error
                )
                this.initRetryTimeout = setTimeout(async () => {
                    await this._setupPlugin(vm)
                }, nextRetryMs)
            } else {
                this.inErroredState = true
                await this.processFatalVmSetupError(error, false)
                await this.createLogEntry(
                    `setupPlugin failed with ${error} (instance ID ${this.hub.instanceId}). Disabled the app!`,
                    PluginLogEntryType.Error
                )
                throw new SetupPluginError(`setupPlugin failed with ${error} for ${logInfo}. Disabled the app!`)
            }
        }
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

    private async processFatalVmSetupError(error: Error, isSystemError: boolean): Promise<void> {
        await processError(this.hub, this.pluginConfig, error)
        await disablePlugin(this.hub, this.pluginConfig.id)
        await this.hub.db.celeryApplyAsync('posthog.tasks.email.send_fatal_plugin_error', [
            this.pluginConfig.id,
            // Using the `updated_at` field for email campaign idempotency. It's safer to provide it to the task
            // from here, because the value DB may change in the DB while the task is queued.
            this.pluginConfig.updated_at || null,
            error.toString(),
            isSystemError,
        ])
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
