import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { LegacyDestinationPlugin, LegacyDestinationPluginMeta } from '../../types'
import metadata from './plugin.json'

export type PaceMetaInput = LegacyDestinationPluginMeta & {
    config: {
        api_key: string
    }
}

export const onEvent = async (event: ProcessedPluginEvent, { config, fetch }: PaceMetaInput): Promise<void> => {
    await fetch('https://data.production.paceapp.com/events', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-api-key': config.api_key,
        },
        body: JSON.stringify({
            data: {
                ...event,
                properties: Object.fromEntries(
                    Object.entries(event.properties || {}).filter(([key, _]) => !key.startsWith('$'))
                ),
            },
        }),
    })
}

export const pacePlugin: LegacyDestinationPlugin = {
    id: 'pace-posthog-integration',
    metadata: metadata as any,
    onEvent,
}
