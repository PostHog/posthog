import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

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
