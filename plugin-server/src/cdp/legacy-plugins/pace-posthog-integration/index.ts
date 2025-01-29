import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { LegacyPlugin, LegacyPluginMeta } from '../types'
import metadata from './plugin.json'

type PaceMetaInput = LegacyPluginMeta & {
    config: {
        api_key: string
    }
}

const onEvent = async (event: ProcessedPluginEvent, { config, fetch }: PaceMetaInput): Promise<void> => {
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
                )
            }
        })
      })
}

export const pacePlugin: LegacyPlugin = {
  id: 'pace',
  metadata: metadata as any,
  setupPlugin: () => Promise.resolve(),
  onEvent,
}
