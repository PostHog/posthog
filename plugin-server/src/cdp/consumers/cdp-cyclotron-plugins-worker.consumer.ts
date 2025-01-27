import { Meta, ProcessedPluginEvent, RetryError, StorageExtension } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Response, trackedFetch } from '~/src/utils/fetch'
import { status } from '~/src/utils/status'

import { PLUGINS_BY_ID } from '../legacy-plugins'
import { LegacyPluginLogger, LegacyPluginMeta } from '../legacy-plugins/types'
import { HogFunctionInvocation, HogFunctionInvocationResult, HogFunctionTypeType } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

type PluginState = {
    setupPromise: Promise<any>
    errored: boolean
    meta: Meta
}

const createStorage = (): StorageExtension => {
    const storage: Record<string, any> = {}
    return {
        get: (key: string) => Promise.resolve(storage[key]),
        set: (key: string, value: any) => {
            storage[key] = value
            return Promise.resolve()
        },
        del: (key: string) => {
            delete storage[key]
            return Promise.resolve()
        },
    }
}

/**
 * NOTE: This is a consumer to take care of legacy plugins.
 */
export class CdpCyclotronWorkerPlugins extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerPlugins'
    protected queue = 'plugin' as const
    protected hogTypes: HogFunctionTypeType[] = ['destination']

    private pluginState: Record<string, PluginState> = {}

    public async processInvocations(invocations: HogFunctionInvocation[]): Promise<HogFunctionInvocationResult[]> {
        const results = await this.runManyWithHeartbeat(invocations, (item) => this.executePluginInvocation(item))

        await this.processInvocationResults(results)
        await this.updateJobs(results)
        await this.produceQueuedMessages()

        return results
    }

    public async fetch(...args: Parameters<typeof trackedFetch>): Promise<Response> {
        return trackedFetch(...args)
    }

    public async executePluginInvocation(invocation: HogFunctionInvocation): Promise<HogFunctionInvocationResult> {
        const result: HogFunctionInvocationResult = {
            invocation,
            finished: true,
            capturedPostHogEvents: [],
            logs: [],
        }

        const pluginId = invocation.hogFunction.template_id?.startsWith('plugin-')
            ? invocation.hogFunction.template_id.replace('plugin-', '')
            : null

        result.logs.push({
            level: 'debug',
            timestamp: DateTime.now(),
            message: `Executing plugin ${pluginId}`,
        })
        const plugin = pluginId ? PLUGINS_BY_ID[pluginId] : null

        if (!plugin || !pluginId) {
            result.error = new Error(`Plugin ${pluginId} not found`)
            result.logs.push({
                level: 'error',
                timestamp: DateTime.now(),
                message: `Plugin ${pluginId} not found`,
            })
            return result
        }

        const addLog = (level: 'debug' | 'warn' | 'error' | 'info', ...args: any[]) => {
            result.logs.push({
                level,
                timestamp: DateTime.now(),
                message: args.join(' '),
            })
        }

        const logger: LegacyPluginLogger = {
            debug: (...args: any[]) => addLog('debug', ...args),
            warn: (...args: any[]) => addLog('warn', ...args),
            log: (...args: any[]) => addLog('info', ...args),
            error: (...args: any[]) => addLog('error', ...args),
        }

        let state = this.pluginState[pluginId]

        if (!state) {
            const meta: LegacyPluginMeta<any> = {
                config: invocation.globals.inputs,
                attachments: {},
                global: {},
                jobs: {},
                metrics: {},
                cache: {} as any,
                storage: createStorage(),
                geoip: {} as any,
                utils: {} as any,
                fetch: (...args) => this.fetch(...args),
                logger: logger,
            }

            state = this.pluginState[pluginId] = {
                setupPromise: plugin.setupPlugin?.(meta) ?? Promise.resolve(),
                meta,
                errored: false,
            }
        }

        try {
            await state.setupPromise
        } catch (e) {
            state.errored = true
            result.error = e
            result.logs.push({
                level: 'error',
                timestamp: DateTime.now(),
                message: `Plugin ${pluginId} setup failed: ${e.message}`,
            })
            return result
        }

        // Convert the invocation into the right interface for the plugin

        const event: ProcessedPluginEvent = {
            distinct_id: invocation.globals.event.distinct_id,
            ip: invocation.globals.event.properties.$ip,
            team_id: invocation.hogFunction.team_id,
            event: invocation.globals.event.event,
            properties: invocation.globals.event.properties,
            timestamp: invocation.globals.event.timestamp,
            $set: invocation.globals.event.properties.$set,
            $set_once: invocation.globals.event.properties.$set_once,
            uuid: invocation.globals.event.uuid,
            person: invocation.globals.person
                ? {
                      uuid: invocation.globals.person.id,
                      team_id: invocation.hogFunction.team_id,
                      properties: invocation.globals.person.properties,
                      created_at: '', // NOTE: We don't have this anymore - see if any plugin uses it...
                  }
                : undefined,
        }

        try {
            status.info('⚡️', 'Executing plugin', {
                pluginId,
                invocationId: invocation.id,
            })
            await plugin.onEvent?.(event, {
                ...state.meta,
                logger,
                fetch: this.fetch,
            })
            result.logs.push({
                level: 'debug',
                timestamp: DateTime.now(),
                message: `Execution successful`,
            })
        } catch (e) {
            if (e instanceof RetryError) {
                // NOTE: Schedule as a retry to cyclotron?
            }

            status.error('💩', 'Plugin errored', {
                error: e,
                pluginId,
                invocationId: invocation.id,
            })

            result.error = e
            result.logs.push({
                level: 'error',
                timestamp: DateTime.now(),
                message: `Plugin errored: ${e.message}`,
            })
        }

        return result
    }
}
