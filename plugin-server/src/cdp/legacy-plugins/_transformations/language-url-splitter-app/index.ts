import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPlugin, LegacyTransformationPluginMeta } from '../../types'
import metadata from './plugin.json'

export function processEvent(event: PluginEvent, { config }: LegacyTransformationPluginMeta) {
    const { pattern, matchGroup, property, replacePattern, replaceKey, replaceValue } = config
    if (event.properties && typeof event.properties['$pathname'] === 'string') {
        const regexp = new RegExp(pattern)
        const match = event.properties['$pathname'].match(regexp)
        if (match) {
            event.properties[property] = match[matchGroup]
            if (replacePattern) {
                const replaceRegexp = new RegExp(replacePattern)
                event.properties[replaceKey] = event.properties['$pathname'].replace(replaceRegexp, replaceValue)
            }
        }
    }
    return event
}

export const languageUrlSplitterApp: LegacyTransformationPlugin = {
    id: 'language-url-splitter-app',
    metadata: metadata as any,
    processEvent,
}
