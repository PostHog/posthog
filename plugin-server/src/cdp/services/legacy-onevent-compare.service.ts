import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { Counter } from 'prom-client'

import { Hub, PluginConfig, PluginMethodsConcrete, PostIngestionEvent } from '~/src/types'
import { Response } from '~/src/utils/fetch'
import { getHttpCallRecorder, HttpCallRecorder, RecordedHttpCall, recordFetchRequest } from '~/src/utils/recorded-fetch'
import { status } from '~/src/utils/status'

import { DESTINATION_PLUGINS } from '../legacy-plugins'
import { HogFunctionInvocation, HogFunctionType } from '../types'
import { createInvocation } from '../utils'
import { LegacyPluginExecutorService } from './legacy-plugin-executor.service'

const comparisonCounter = new Counter({
    name: 'legacy_onevent_comparison_count',
    help: 'The number of legacy onevent comparisons',
    labelNames: ['plugin_id', 'matches'],
})

function convertPluginConfigToHogFunction(pluginConfig: PluginConfig): HogFunctionType | null {
    const url = pluginConfig.plugin?.url
    const pluginId = url?.replace('inline://', '').replace('https://github.com/PostHog/', '')
    const hogFunctionTemplateId = `plugin-${pluginId}`

    const legacyDestinationPlugin = DESTINATION_PLUGINS.find((plugin) => plugin.template.id === hogFunctionTemplateId)

    if (!legacyDestinationPlugin) {
        status.error('🔍', `Legacy destination plugin ${hogFunctionTemplateId} not found`)
        return null
    }

    const hogFunction: HogFunctionType = {
        id: `hog-plugin-config-${pluginConfig.id}`,
        template_id: legacyDestinationPlugin.template.id,
        team_id: pluginConfig.team_id,
        type: 'destination',
        name: `Comparison hog function for plugin config - ${pluginConfig.id} (${pluginConfig.plugin?.name})`,
        enabled: true,
        deleted: false,
        hog: '',
        bytecode: [],
        inputs_schema: legacyDestinationPlugin.template.inputs_schema,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        inputs: {},
    }

    const inputs: HogFunctionType['inputs'] = {}

    if (pluginId === 'customerio-plugin') {
        // These are plugins that use the legacy storage
        inputs['legacy_plugin_config_id'] = { value: pluginConfig.id }
    }

    for (const [key, value] of Object.entries(pluginConfig.config)) {
        inputs[key] = { value }
    }

    hogFunction.inputs = inputs

    return hogFunction
}

export class LegacyOneventCompareService {
    legacyPluginExecutorService: LegacyPluginExecutorService
    hogFunctionsByPluginConfigId: Record<string, HogFunctionType | null>

    constructor(private hub: Hub) {
        this.legacyPluginExecutorService = new LegacyPluginExecutorService(this.hub)
        this.hogFunctionsByPluginConfigId = {}
    }

    get shouldCompare(): boolean {
        return this.hub.DESTINATION_MIGRATION_DIFFING_ENABLED === true && this.hub.TASKS_PER_WORKER === 1
    }

    getOrCreateHogFunction(pluginConfig: PluginConfig): HogFunctionType | null {
        // We do essentially what the python migration code does to convert a plugin config into a hog function
        if (!this.hogFunctionsByPluginConfigId[pluginConfig.id]) {
            let hogFunction: HogFunctionType | null = null
            try {
                hogFunction = convertPluginConfigToHogFunction(pluginConfig)
            } catch (e) {
                status.error('Failed to convert plugin config to hog function', e)
            }

            this.hogFunctionsByPluginConfigId[pluginConfig.id] = hogFunction
        }

        return this.hogFunctionsByPluginConfigId[pluginConfig.id]
    }

    /**
     * Temporary code path designed for 1-1 testing of inlined JS plugins with legacy plugins.
     */
    async runOnEvent(
        pluginConfig: PluginConfig,
        onEvent: PluginMethodsConcrete['onEvent'],
        event: PostIngestionEvent,
        onEventPayload: ProcessedPluginEvent
    ): Promise<void> {
        if (!this.shouldCompare) {
            return onEvent(onEventPayload)
        }

        // Clear the recorder before running the operation if recording is enabled

        let pluginConfigError: any = null
        let recordedCalls: RecordedHttpCall[] = []
        try {
            // Execute the operation
            await onEvent(onEventPayload)
        } catch (e) {
            pluginConfigError = e
        } finally {
            recordedCalls = getHttpCallRecorder().getCalls()
            getHttpCallRecorder().clearCalls()
        }

        try {
            const hogFunctionResult = await this.runHogFunctionOnEvent(pluginConfig, event, recordedCalls)
            const comparer = new HttpCallRecorder()

            const comparison = comparer.compareCalls(recordedCalls, hogFunctionResult.recordedCalls)

            comparisonCounter
                .labels(pluginConfig.plugin?.id.toString() ?? '?', comparison.matches ? 'true' : 'false')
                .inc()

            if (!comparison.matches) {
                status.info('🔎', `COMPARING ${pluginConfig.plugin?.id}`, comparison)
            }
        } catch (e) {
            status.error('', 'Failed to compare HTTP calls', e)
        }

        // Throw the original error so it behaves like before
        if (pluginConfigError) {
            throw pluginConfigError
        }
    }

    async runHogFunctionOnEvent(
        pluginConfig: PluginConfig,
        event: PostIngestionEvent,
        recordedCalls: RecordedHttpCall[]
    ): Promise<{
        error?: any
        recordedCalls: RecordedHttpCall[]
    }> {
        // Try to execute the same thing but polyfilling the fetch calls with the recorded ones

        const hogFunction = this.getOrCreateHogFunction(pluginConfig)

        if (!hogFunction) {
            throw new Error(`Failed to convert plugin config to hog function: ${pluginConfig.id}`)
        }

        // Mapped plugin config inputs are always static values
        const inputs: HogFunctionInvocation['globals']['inputs'] = Object.fromEntries(
            Object.entries(hogFunction.inputs ?? {}).map(([key, value]) => [key, value.value])
        )

        const invocation = createInvocation(
            {
                project: {
                    id: event.teamId,
                    name: '', // NOTE: Not used
                    url: '', // NOTE: Not used
                },
                event: {
                    distinct_id: event.distinctId,
                    elements_chain: '',
                    event: event.event,
                    properties: event.properties,
                    uuid: event.eventUuid,
                    timestamp: event.timestamp,
                    url: '', // NOTE: Not used
                },
                person: event.person_id
                    ? {
                          id: event.person_id,
                          properties: event.person_properties,
                          name: '', // NOTE: Not used
                          url: '', // NOTE: Not used
                      }
                    : undefined,
                inputs,
            },
            hogFunction
        )

        const copiedCalls = [...recordedCalls]
        const recorder = new HttpCallRecorder()

        let error: any = undefined

        await this.legacyPluginExecutorService
            .execute(invocation, {
                fetch: (url, init) => {
                    // For each call take the first one out of the stack

                    const call = copiedCalls.shift()

                    if (!call) {
                        throw new Error('No call found')
                    }

                    if (call?.request.url !== url) {
                        throw new Error(`Call URL ${url} did not match expected URL ${call?.request.url}`)
                    }

                    const request = recordFetchRequest(url, init)

                    recorder.addCall({
                        id: call.id,
                        request,
                        response: call.response,
                    })

                    const res: Partial<Response> = {
                        headers: call.response.headers as any,
                        status: call.response.status,
                        statusText: call.response.statusText,
                        ok: call.response.status >= 200 && call.response.status < 300,
                        json: () => {
                            return new Promise((res, rej) => {
                                if (!call.response.body) {
                                    return rej(new Error('No response body'))
                                }
                                try {
                                    return res(JSON.parse(call.response.body))
                                } catch (e) {
                                    return rej(e)
                                }
                            })
                        },
                    }

                    return Promise.resolve(res as Response)
                },
            })
            .catch((e) => {
                error = e
            })

        // Do comparison of calls!

        return { error, recordedCalls: recorder.getCalls() }
    }
}
