import { Meta, ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { PLUGINS_BY_ID } from '../legacy-plugins/manager'
import { HogFunctionInvocation, HogFunctionInvocationResult, HogFunctionTypeType } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

type PluginState = {
    setupPromise: Promise<any>
    meta: Meta
}

const PLUGIN_STATE: Record<string, PluginState> = {}

/**
 * NOTE: This is a consumer to take care of legacy plugins.
 */
export class CdpCyclotronWorkerPlugins extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerPlugins'
    protected queue = 'plugins' as const
    protected hogTypes: HogFunctionTypeType[] = ['destination']

    public async processInvocations(invocations: HogFunctionInvocation[]): Promise<HogFunctionInvocationResult[]> {
        return await this.runManyWithHeartbeat(invocations, (item) => this.executePluginInvocation(item))
    }

    private async executePluginInvocation(invocation: HogFunctionInvocation): Promise<HogFunctionInvocationResult> {
        const result: HogFunctionInvocationResult = {
            invocation,
            finished: true,
            capturedPostHogEvents: [],
            logs: [],
        }

        const pluginId = invocation.hogFunction.template_id?.startsWith('plugin-')
            ? invocation.hogFunction.template_id
            : `plugin-${invocation.hogFunction.template_id}`

        result.logs.push({
            level: 'debug',
            timestamp: DateTime.now(),
            message: `Executing plugin ${pluginId}`,
        })
        const plugin = PLUGINS_BY_ID[pluginId]

        if (!plugin) {
            result.error = new Error(`Plugin ${pluginId} not found`)
            result.logs.push({
                level: 'error',
                timestamp: DateTime.now(),
                message: `Plugin ${pluginId} not found`,
            })
            return result
        }

        // Convert the invocation into the right interface for the plugin

        const inputs = invocation.globals.inputs

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

        let state = PLUGIN_STATE[pluginId]

        if (!state) {
            const meta: Meta = {
                global: inputs,
                attachments: {},
                config: {},
                jobs: {},
                metrics: {},
                cache: {} as any,
                storage: {} as any, // NOTE: Figuree out what to do about storage as that is used...
                geoip: {} as any,
                utils: {} as any,
            }

            state = PLUGIN_STATE[pluginId] = {
                setupPromise: plugin.setupPlugin?.(meta) ?? Promise.resolve(),
                meta,
            }
        }

        await state.setupPromise

        await plugin.onEvent?.(event, {
            ...state.meta,
            global: inputs,
        })

        return result
    }
}
