import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig, PluginMethodsConcrete, PostIngestionEvent } from '~/src/types'
import { getHttpCallRecorder, RecordedHttpCall } from '~/src/utils/recorded-fetch'
import { status } from '~/src/utils/status'

import { DESTINATION_PLUGINS } from '../legacy-plugins'
import { HogFunctionInvocation, HogFunctionType } from '../types'
import { createInvocation } from '../utils'
import { LegacyPluginExecutorService } from './legacy-plugin-executor.service'

/**
 * Logs HTTP calls made by a plugin
 */
function logHttpCalls(
    recordedCalls: RecordedHttpCall[],
    eventUuid: string | undefined,
    pluginConfig: PluginConfig,
    failed: boolean = false
): void {
    if (recordedCalls.length > 0) {
        const actionText = failed ? 'before failing' : 'during operation'

        status.info(
            '🌐',
            `Plugin ${pluginConfig.plugin?.name || 'unknown'} (${pluginConfig.id}) made ${
                recordedCalls.length
            } HTTP calls ${actionText} for event ${eventUuid || 'unknown'}`
        )

        // Log details about each call
        recordedCalls.forEach((call: RecordedHttpCall, index: number) => {
            status.info(
                '🌐',
                `Event ${eventUuid || 'unknown'} - Call ${index + 1}: ${call.request.method} ${
                    call.request.url
                } - Status: ${call.response.status}`
            )

            // Log errors if any
            if (call.error) {
                status.error('🌐', `Event ${eventUuid || 'unknown'} - Call ${index + 1} error: ${call.error.message}`)
            }
        })
    }
}

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
        getHttpCallRecorder().clearCalls()

        let pluginConfigError: any = null
        let hogFunctionError: any = null
        try {
            // Execute the operation
            await onEvent(onEventPayload)
        } catch (e) {
            pluginConfigError = e
        }

        try {
            const recordedCalls = getHttpCallRecorder().getCalls()
            await this.runHogFunctionOnEvent(pluginConfig, event, recordedCalls)
        } catch (e) {
            hogFunctionError = e
        }

        // Do the actual comparison of results

        // Throw the original error so it behaves like before
        if (pluginConfigError) {
            throw pluginConfigError
        }
    }

    async runHogFunctionOnEvent(
        pluginConfig: PluginConfig,
        event: PostIngestionEvent,
        recordedCalls: RecordedHttpCall[]
    ): Promise<void> {
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

        await this.legacyPluginExecutorService.execute(invocation)
    }
}
