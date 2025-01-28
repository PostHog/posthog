import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyPluginMeta } from '../../types'
import { LegacyTransformationPlugin } from '../../types'
import metadata from './plugin.json'

function normalizeUrl(url: string): string {
    try {
        const parsedUrl = new URL(url.toLocaleLowerCase())
        parsedUrl.pathname = parsedUrl.pathname.replace(/\/$/, '')

        return parsedUrl.toString()
    } catch (err) {
        throw `Unable to normalize invalid URL: "${url}"`
    }
}

export function processEvent(event: PluginEvent, { logger }: LegacyPluginMeta) {
    const $current_url = event?.properties?.$current_url
    if (event?.properties && $current_url) {
        const normalized_url = normalizeUrl($current_url)
        event.properties.$current_url = normalized_url

        logger.debug(`event.$current_url: "${$current_url}" normalized to "${normalized_url}"`)
    }

    return event
}

export const posthogUrlNormalizerPlugin: LegacyTransformationPlugin = {
    id: 'posthog-url-normalizer-plugin',
    metadata: metadata as any,
    processEvent,
}
