import { PluginEvent, PluginMeta } from '@posthog/plugin-scaffold'
import { createHash } from 'crypto'

export function setupPlugin({ config, global }: PluginMeta) {
    const percentage = parseFloat(config.percentage)
    if (isNaN(percentage) || percentage > 100 || percentage < 0) {
        throw new Error('Percentage must be a number between 0 and 100.')
    }
    global.percentage = percentage
    global.randomSampling = config.samplingMethod === 'Random sampling'
}

// /* Runs on every event */
export function processEvent(event: PluginEvent, { global }: PluginMeta) {

    // hash is a sha256 hash of the distinct_id represented in base 16
    // We take the first 15 digits, convert this into an integer, 
    // dividing by the biggest 15 digit, base 16 number to get a value between 0 and 1.
    // This is stable, so a distinct_id that was allowed before will continue to be allowed,
    // even if the percentage increases


    let shouldIngestEvent = true
    if (global.randomSampling) {
        shouldIngestEvent = parseInt(Math.random()*100) <= global.percentage
    } else {
        const hash = createHash("sha256")
            .update(event.distinct_id)
            .digest("hex")
        const decisionValue = parseInt(hash.substring(0, 15), 16) / 0xfffffffffffffff
        shouldIngestEvent = decisionValue <= global.percentage / 100
    }

    if (shouldIngestEvent) {
        return event
    }
    return null
}
