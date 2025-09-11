import { ProcessedPluginEvent, RetryError } from '@posthog/plugin-scaffold'

import { FetchResponse } from '../../../../utils/request'
import { LegacyDestinationPluginMeta } from '../../types'

export type PatternsMeta = LegacyDestinationPluginMeta & {
    config: {
        webhookUrl: string
        allowedEventTypes: string
    }
    global: {
        allowedEventTypesSet: Set<string>
    }
}

// Plugin method that runs on plugin load
export async function setupPlugin({ config, global }: PatternsMeta): Promise<void> {
    if (config.allowedEventTypes) {
        let allowedEventTypes = config.allowedEventTypes.split(',')
        allowedEventTypes = allowedEventTypes.map((eventType: string) => eventType.trim())
        global.allowedEventTypesSet = new Set(allowedEventTypes)
    }
    return Promise.resolve()
}

// Plugin method to export events
export const onEvent = async (event: ProcessedPluginEvent, { config, global, fetch }: PatternsMeta): Promise<void> => {
    if (global.allowedEventTypesSet) {
        if (!global.allowedEventTypesSet.has(event.event)) {
            return
        }
    }

    const response: FetchResponse = await fetch(config.webhookUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([event]),
    })

    if (response.status != 200) {
        const data = await response.text()
        throw new RetryError(`Export events failed: ${data}`)
    }
}
