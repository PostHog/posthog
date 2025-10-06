import { createHash } from 'crypto'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

export function setupPlugin({ config, global }: LegacyTransformationPluginMeta) {
    const percentage = parseFloat(config.percentage)
    if (isNaN(percentage) || percentage > 100 || percentage < 0) {
        throw new Error('Percentage must be a number between 0 and 100.')
    }
    global.percentage = percentage
    global.randomSampling = config.samplingMethod === 'Random sampling'
    global.triggeringEvents =
        (config.triggeringEvents ?? '').trim() === ''
            ? []
            : config.triggeringEvents.split(',').map((event: string) => event.trim())
}

// /* Runs on every event */
export function processEvent(event: PluginEvent, { global }: LegacyTransformationPluginMeta) {
    // hash is a sha256 hash of the distinct_id represented in base 16
    // We take the first 15 digits, convert this into an integer,
    // dividing by the biggest 15 digit, base 16 number to get a value between 0 and 1.
    // This is stable, so a distinct_id that was allowed before will continue to be allowed,
    // even if the percentage increases

    let shouldIngestEvent = true
    if (global.triggeringEvents.length === 0 || global.triggeringEvents.includes(event.event)) {
        if (global.randomSampling) {
            shouldIngestEvent = Math.round(Math.random() * 100) <= global.percentage
        } else {
            const hash = createHash('sha256').update(event.distinct_id).digest('hex')
            // eslint-disable-next-line @typescript-eslint/no-loss-of-precision
            const decisionValue = parseInt(hash.substring(0, 15), 16) / 0xfffffffffffffff
            shouldIngestEvent = decisionValue <= global.percentage / 100
        }
    }

    if (shouldIngestEvent) {
        return event
    }
    return null
}
