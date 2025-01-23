import { Meta, ProcessedPluginEvent, RetryError } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { trackedFetch } from '~/src/utils/fetch'

import { PLUGINS_BY_ID } from '../legacy-plugins'
import { FetchType, MetaWithFetch } from '../legacy-plugins/types'
import { HogFunctionInvocation, HogFunctionInvocationResult, HogFunctionTypeType } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

type PluginState = {
    setupPromise: Promise<any>
    errored: boolean
    meta: Meta
}

/**
 * NOTE: This is a consumer to take care of legacy plugins.
 */
export class CdpCyclotronWorkerPlugins extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerPlugins'
    protected queue = 'plugins' as const
    protected hogTypes: HogFunctionTypeType[] = ['destination']

    private pluginState: Record<string, PluginState> = {}

    public async processInvocations(invocations: HogFunctionInvocation[]): Promise<HogFunctionInvocationResult[]> {
        return await this.runManyWithHeartbeat(invocations, (item) => this.executePluginInvocation(item))
    }

    public fetch(...args: Parameters<FetchType>) {
        // TOOD: THis better
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

        let state = this.pluginState[pluginId]

        if (!state) {
            const meta: MetaWithFetch = {
                config: invocation.globals.inputs,
                attachments: {},
                global: {},
                jobs: {},
                metrics: {},
                cache: {} as any,
                storage: {} as any, // NOTE: Figuree out what to do about storage as that is used...
                geoip: {} as any,
                utils: {} as any,
                fetch: this.fetch as any,
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
                message: `Plugin ${pluginId} setup failed`,
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
            await plugin.onEvent?.(event, state.meta)
            result.logs.push({
                level: 'debug',
                timestamp: DateTime.now(),
                message: `Plugin ${pluginId} execution successful`,
            })
        } catch (e) {
            if (e instanceof RetryError) {
                // NOTE: Schedule as a retry to cyclotron?
            }
            result.error = e
            result.logs.push({
                level: 'error',
                timestamp: DateTime.now(),
                message: `Plugin ${pluginId} execution failed`,
            })
        }

        return result
    }
}
