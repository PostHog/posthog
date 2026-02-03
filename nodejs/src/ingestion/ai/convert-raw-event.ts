import { PluginEvent } from '@posthog/plugin-scaffold'

import { convertOtelEvent } from './otel'

export function convertRawEvent(event: PluginEvent): void {
    if (event.properties?.$ai_ingestion_source === 'otel') {
        const debug = !!event.properties['posthog.ai.debug']
        const rawProperties = debug ? structuredClone(event.properties) : undefined

        convertOtelEvent(event)

        if (debug) {
            event.properties.$ai_debug = true
            event.properties.$ai_debug_data = rawProperties
        }
    }
}
