import { RetryError } from '@posthog/plugin-scaffold'
import equal from 'fast-deep-equal'
import { Counter, Summary } from 'prom-client'
import { VM } from 'vm2'

import {
    Hub,
    PluginConfig,
    PluginConfigVMResponse,
    PluginLogEntrySource,
    PluginLogEntryType,
    PluginMethods,
    PluginTask,
    PluginTaskType,
} from '../../types'
import { processError } from '../../utils/db/error'
import { getPlugin, setPluginCapabilities } from '../../utils/db/sql'
import { instrument } from '../../utils/metrics'
import { getNextRetryMs } from '../../utils/retries'
import { status } from '../../utils/status'
import { pluginDigest } from '../../utils/utils'
import { getVMPluginCapabilities, shouldSetupPluginInServer } from '../vm/capabilities'
import { constructInlinePluginInstance } from './inline/inline'
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

const pluginSetupMsSummary = new Summary({
    name: 'plugin_setup_ms',
    help: 'Time to setup plugins',
    labelNames: ['plugin_id', 'status'],
})
const pluginDisabledBySystemCounter = new Counter({
    name: 'plugin_disabled_by_system',
    help: 'Count of plugins disabled by the system',
    labelNames: ['plugin_id'],
})

export function constructPluginInstance(hub: Hub, pluginConfig: PluginConfig): PluginInstance {
    if (pluginConfig.plugin?.plugin_type == 'inline') {
        return constructInlinePluginInstance(hub, pluginConfig)
    }
    return new LazyPluginVM(hub, pluginConfig)
}

export interface PluginInstance {
    // These are "optional", but if they're not set, loadPlugin will fail
    initialize?: (indexJs: string, logInfo: string) => Promise<void>
    failInitialization?: () => void

    getTeardown: () => Promise<PluginMethods['teardownPlugin'] | null>
    getTask: (name: string, type: PluginTaskType) => Promise<PluginTask | null>
    getScheduledTasks: () => Promise<Record<string, PluginTask>>
    getPluginMethod: <T extends keyof PluginMethods>(method_name: T) => Promise<PluginMethods[T] | null>
    clearRetryTimeoutIfExists: () => void
    setupPluginIfNeeded: () => Promise<boolean>

    createLogEntry: (message: string, logType?: PluginLogEntryType) => Promise<void>

    // This is only used for metrics, and can probably be dropped as we start to care less about
    // what imports are used by plugins (or as inlining more plugins makes imports irrelevant)
    usedImports: Set<string> | undefined
}

export class LazyPluginVM implements PluginInstance {
    initialize?: (indexJs: string, logInfo: string) => Promise<void>
    failInitialization?: () => void
    resolveInternalVm!: Promise<PluginConfigVMResponse | null>
    usedImports: Set<string> | undefined
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

    public async getTeardown(): Promise<PluginConfigVMResponse['methods']['teardownPlugin'] | null> {
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

    public async getPluginMethod<T extends keyof PluginMethods>(method_name: T): Promise<PluginMethods[T] | null> {
        let method = (await this.resolveInternalVm)?.methods[method_name] || null
        if (!this.ready && method) {
            const pluginReady = await this.setupPluginIfNeeded()
            if (!pluginReady) {
                method = null
            }
        }
        return method
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
                    this.usedImports = vm.usedImports
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
                    status.debug('🔌', `Loaded ${logInfo}.`)
                    await this.createLogEntry(
                        `Plugin loaded (instance ID ${this.hub.instanceId}).`,
                        PluginLogEntryType.Debug
                    )
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
                await instrument(
                    {
                        metricName: 'vm.setup',
                        key: 'plugin',
                        tag: this.pluginConfig.plugin?.name || '?',
                    },
                    () => this._setupPlugin(vm)
                )
            } catch (error) {
                status.warn('⚠️', error.message)
                return false
            }
        }
        return true
    }

    // TODO - this is only called in tests, try to remove at some point.
    public async _setupPlugin(vm?: VM): Promise<void> {
        const logInfo = this.pluginConfig.plugin
            ? pluginDigest(this.pluginConfig.plugin)
            : `plugin config ID '${this.pluginConfig.id}'`
        this.totalInitAttemptsCounter++
        const pluginId = this.pluginConfig.plugin?.id.toString() || 'unknown'
        const timer = new Date()
        try {
            // Make sure one can't self-replicate resulting in an infinite loop
            if (this.pluginConfig.plugin && this.pluginConfig.plugin.name == 'Replicator') {
                const host = this.pluginConfig.config['host']
                const apiKey = String(this.pluginConfig.config['project_api_key'])
                const team = await this.hub.teamManager.fetchTeam(this.pluginConfig.team_id)
                // There's a single team with replication for the same api key from US to EU
                // otherwise we're just checking that token differs to better safeguard against forwarding
                const isAllowed = team?.uuid == '017955d2-b09f-0000-ec00-2116c7e8a605' && host == 'eu.posthog.com'
                if (!isAllowed && team?.api_token.trim() == apiKey.trim()) {
                    throw Error('Self replication is not allowed')
                }
                // Only default org can use higher than 1x replication
                if (
                    team?.organization_id != '4dc8564d-bd82-1065-2f40-97f7c50f67cf' &&
                    this.pluginConfig.config['replication'] != 1
                ) {
                    throw Error('Only 1x replication is allowed')
                }
            }
            await vm?.run(`${this.vmResponseVariable}.methods.setupPlugin?.()`)
            pluginSetupMsSummary
                .labels({ plugin_id: pluginId, status: 'success' })
                .observe(new Date().getTime() - timer.getTime())
            this.ready = true

            status.info('🔌', `setupPlugin succeeded for ${logInfo}.`)
            await this.createLogEntry(
                `setupPlugin succeeded (instance ID ${this.hub.instanceId}).`,
                PluginLogEntryType.Debug
            )
        } catch (error) {
            pluginSetupMsSummary
                .labels({ plugin_id: pluginId, status: 'fail' })
                .observe(new Date().getTime() - timer.getTime())

            this.clearRetryTimeoutIfExists()
            if (error instanceof RetryError) {
                error._attempt = this.totalInitAttemptsCounter
                error._maxAttempts = VM_INIT_MAX_RETRIES
            }
            if (error instanceof RetryError && this.totalInitAttemptsCounter < VM_INIT_MAX_RETRIES) {
                const nextRetryMs = getNextRetryMs(
                    INITIALIZATION_RETRY_BASE_MS,
                    INITIALIZATION_RETRY_MULTIPLIER,
                    this.totalInitAttemptsCounter
                )
                const nextRetryInfo = `Retrying in ${nextRetryMs / 1000} s...`
                status.warn('⚠️', `setupPlugin failed with ${error} for ${logInfo}. ${nextRetryInfo}`)
                await this.createLogEntry(
                    `setupPlugin failed with ${error} (instance ID ${this.hub.instanceId}). ${nextRetryInfo}`,
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

    public async createLogEntry(message: string, logType = PluginLogEntryType.Info): Promise<void> {
        await this.hub.db.queuePluginLogEntry({
            message,
            pluginConfig: this.pluginConfig,
            source: PluginLogEntrySource.System,
            type: logType,
            instanceId: this.hub.instanceId,
        })
    }

    private async processFatalVmSetupError(error: Error, isSystemError: boolean): Promise<void> {
        pluginDisabledBySystemCounter.labels(this.pluginConfig.plugin?.id.toString() || 'unknown').inc()
        await processError(this.hub, this.pluginConfig, error)
        // Temp disabled on 26/09/24, due to customer issue. TODO - we should actually disable in the case of bad plugin configs, assuming we revisit this before throwing the whole plugin concept out
        // await disablePlugin(this.hub, this.pluginConfig.id)
        await this.hub.celery.applyAsync('posthog.tasks.plugin_server.fatal_plugin_error', [
            this.pluginConfig.id,
            // Using the `updated_at` field for email campaign idempotency. It's safer to provide it to the task
            // from here, because the value DB may change in the DB while the task is queued.
            this.pluginConfig.updated_at || null,
            error.toString(),
            isSystemError,
        ])
    }

    private async updatePluginCapabilitiesIfNeeded(vm: PluginConfigVMResponse): Promise<void> {
        const capabilities = getVMPluginCapabilities(vm.methods, vm.tasks)

        const prevCapabilities = this.pluginConfig.plugin!.capabilities
        if (!equal(prevCapabilities, capabilities)) {
            await setPluginCapabilities(this.hub, this.pluginConfig.plugin_id, capabilities)
            this.pluginConfig.plugin!.capabilities = capabilities
        }
    }
}

export async function populatePluginCapabilities(hub: Hub, pluginId: number): Promise<void> {
    status.info('🔌', `Populating plugin capabilities for plugin ID ${pluginId}...`)
    const plugin = await getPlugin(hub, pluginId)
    if (!plugin) {
        status.error('🔌', `Plugin with ID ${pluginId} not found for populating capabilities.`)
        return
    }
    if (!plugin.source__index_ts) {
        status.error('🔌', `Plugin with ID ${pluginId} has no index.ts file for populating capabilities.`)
        return
    }

    const { methods, tasks } = createPluginConfigVM(
        hub,
        {
            id: 0,
            plugin: plugin,
            plugin_id: plugin.id,
            team_id: 0,
            enabled: false,
            order: 0,
            created_at: '0',
            config: {},
        },
        plugin.source__index_ts || ''
    )
    const capabilities = getVMPluginCapabilities(methods, tasks)

    const prevCapabilities = plugin.capabilities
    if (!equal(prevCapabilities, capabilities)) {
        await setPluginCapabilities(hub, pluginId, capabilities)
    }
}
