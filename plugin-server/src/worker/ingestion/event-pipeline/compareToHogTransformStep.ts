import { PluginEvent } from '@posthog/plugin-scaffold'
import { Counter } from 'prom-client'

import { HogTransformerService } from '../../../cdp/hog-transformations/hog-transformer.service'
import { status } from '../../../utils/status'
import { cloneObject } from '../../../utils/utils'

type Diff = {
    key: string
    plugins: string
    hog: string
}

export const counterHogTransformationDiff = new Counter({
    name: 'hog_transformation_diff',
    help: 'Whether the hog transformations produced the same event as the plugin',
    labelNames: ['outcome'], // either same or diff
})

// We don't care about plugin only properties
const IGNORE_PROPERTIES = ['$plugins_failed', '$plugins_succeeded']

export const compareEvents = (pluginEvent: PluginEvent, hogEvent: PluginEvent): Diff[] => {
    // Comparing objects is expensive so we will do this instead by iterating over the keys we care about

    if (pluginEvent.event !== hogEvent.event) {
        return [{ key: 'event', plugins: pluginEvent.event, hog: hogEvent.event }]
    }

    if (pluginEvent.distinct_id !== hogEvent.distinct_id) {
        return [{ key: 'distinct_id', plugins: pluginEvent.distinct_id, hog: hogEvent.distinct_id }]
    }

    const pluginProperties = Object.keys(pluginEvent.properties ?? {}).sort()

    const diffs: Diff[] = []
    // Compare each property individually
    pluginProperties.forEach((property) => {
        if (IGNORE_PROPERTIES.includes(property)) {
            return
        }

        const pluginValue = pluginEvent.properties?.[property]
        const hogValue = hogEvent.properties?.[property]

        if (JSON.stringify(pluginValue) !== JSON.stringify(hogValue)) {
            diffs.push({ key: `properties.${property}`, plugins: pluginValue, hog: hogValue })
        }
    })

    return diffs
}

export async function compareToHogTransformStep(
    hogTransformer: HogTransformerService | null,
    prePluginsEvent: PluginEvent,
    postPluginsEvent: PluginEvent | null
): Promise<void> {
    if (!hogTransformer) {
        return
    }

    try {
        // TRICKY: We really want to make sure that the other event is unaffected
        const clonedEvent = cloneObject(prePluginsEvent)
        const result = await hogTransformer.transformEvent(clonedEvent, true)
        const hogEvent = result.event

        if (!hogEvent || !postPluginsEvent) {
            if (!hogEvent && !postPluginsEvent) {
                status.info('✅', 'Both plugin and hog transformation produced no event')
                counterHogTransformationDiff.inc({ outcome: 'same' })
            } else if (!hogEvent && postPluginsEvent) {
                status.warn('⚠️', 'Hog transformation produced no event but the plugin did')
                counterHogTransformationDiff.inc({ outcome: 'diff' })
            } else if (hogEvent && !postPluginsEvent) {
                status.warn('⚠️', 'Hog transformation produced an event but the plugin did not')
                counterHogTransformationDiff.inc({ outcome: 'diff' })
            }
            return
        }

        const diffs = compareEvents(postPluginsEvent, hogEvent)
        if (diffs.length > 0) {
            status.warn('⚠️', 'Hog transformation was different from plugin', {
                team_id: prePluginsEvent.team_id,
                diffs,
            })
            counterHogTransformationDiff.inc({ outcome: 'diff' })
        } else {
            status.info('✅', 'Both plugin and hog transformation produced the same event')
            counterHogTransformationDiff.inc({ outcome: 'same' })
        }
    } catch (error) {
        status.error('Error occurred when comparing plugin event to hog transform', error)
    }
}
