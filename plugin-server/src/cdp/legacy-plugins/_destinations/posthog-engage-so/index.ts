import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { LegacyDestinationPlugin, LegacyDestinationPluginMeta } from '../../types'
import metadata from './plugin.json'

type EngagePluginEvent = ProcessedPluginEvent & {
    config?: any
}

const onEvent = async (_event: EngagePluginEvent, { config, fetch }: LegacyDestinationPluginMeta): Promise<void> => {
    const event = _event.event
    if (event.startsWith('$')) {
        // only process a specific set of custom events
        if (!['$identify', '$groupidentify', '$set', '$unset', '$create_alias'].includes(event)) {
            return
        }
    }
    // Ignore plugin events
    if (event.startsWith('plugin')) {
        return
    }

    const auth = 'Basic ' + Buffer.from(`${config.publicKey}:${config.secret}`).toString('base64')
    delete config.publicKey
    delete config.secret
    _event.config = config

    await fetch('https://api.engage.so/posthog', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Authorization: auth,
        },
        body: JSON.stringify(_event),
    })
}

export const engagePlugin: LegacyDestinationPlugin = {
    id: 'posthog-engage-so-plugin',
    metadata: metadata as any,
    onEvent,
}
