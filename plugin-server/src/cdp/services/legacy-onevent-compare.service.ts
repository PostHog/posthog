import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { number } from 'zod'

import { Hub, PluginConfig, PluginMethodsConcrete, PostIngestionEvent } from '~/src/types'
import { captureException } from '~/src/utils/posthog'
import { getHttpCallRecorder, RecordedHttpCall } from '~/src/utils/recorded-fetch'
import { status } from '~/src/utils/status'

import { DESTINATION_PLUGINS } from '../legacy-plugins'
import { HogFunctionType } from '../types'
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

/**
 * Executes an operation while recording HTTP calls if enabled.
 * This function encapsulates the logic for recording HTTP calls during plugin operations.
 */
async function withHttpCallRecording<T>(
    hub: Hub,
    eventUuid: string | undefined,
    pluginConfig: PluginConfig,
    operation: () => Promise<T>
): Promise<T> {
    // Check if we should record HTTP calls - using the same condition as in recorded-fetch.ts
    const recordHttpCalls = hub.DESTINATION_MIGRATION_DIFFING_ENABLED === true && hub.TASKS_PER_WORKER === 1

    // Clear the recorder before running the operation if recording is enabled
    if (recordHttpCalls) {
        getHttpCallRecorder().clearCalls()
    }

    let failed = false
    try {
        // Execute the operation
        return await operation()
    } catch (error) {
        failed = true
        throw error // Re-throw the error to be handled by the caller
    } finally {
        try {
            if (recordHttpCalls) {
                // Get recorded HTTP calls even if the operation failed
                const recordedCalls = getHttpCallRecorder().getCalls()
                logHttpCalls(recordedCalls, eventUuid, pluginConfig, failed)
            }
        } catch (e) {
            status.error('🌐', `Error checking record logs...`)
            captureException(e)
        } finally {
            if (recordHttpCalls) {
                // Clear the recorder to prevent memory leaks
                getHttpCallRecorder().clearCalls()
            }
        }
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
    runOnEvent(
        pluginConfig: PluginConfig,
        onEvent: PluginMethodsConcrete['onEvent'],
        event: PostIngestionEvent,
        onEventPayload: ProcessedPluginEvent
    ): Promise<void> {
        return withHttpCallRecording(this.hub, event.eventUuid, pluginConfig, async () => {
            await onEvent(onEventPayload)
        })
    }
}
