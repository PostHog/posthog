import { PluginEvent } from '@posthog/plugin-scaffold'
import { Counter } from 'prom-client'

import { cloneObject } from '~/src/utils/utils'

import { HogTransformerService } from '../../../cdp/hog-transformations/hog-transformer.service'
import { status } from '../../../utils/status'

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

export const compareEvents = (pluginEvent: PluginEvent, hogEvent: PluginEvent): Diff | null => {
    // Comparing objects is expensive so we will do this instead by iterating over the keys we care about

    if (pluginEvent.event !== hogEvent.event) {
        return { key: 'event', plugins: pluginEvent.event, hog: hogEvent.event }
    }

    if (pluginEvent.distinct_id !== hogEvent.distinct_id) {
        return { key: 'distinct_id', plugins: pluginEvent.distinct_id, hog: hogEvent.distinct_id }
    }

    const pluginProperties = Object.keys(pluginEvent.properties ?? {}).sort()
    const hogProperties = Object.keys(hogEvent.properties ?? {}).sort()

    // Loosely compare the two events by comparing the properties
    if (pluginProperties.length !== hogProperties.length) {
        return { key: 'properties', plugins: pluginProperties.join(','), hog: hogProperties.join(',') }
    }

    // Compare each property individually
    const diffProperties = pluginProperties.filter((property) => {
        const pluginValue = pluginEvent.properties?.[property]
        const hogValue = hogEvent.properties?.[property]

        return JSON.stringify(pluginValue) === JSON.stringify(hogValue)
    })

    if (diffProperties.length > 0) {
        return { key: 'properties', plugins: diffProperties.join(','), hog: diffProperties.join(',') }
    }

    return null
}

export async function compareToHogTransformStep(
    hogTransformer: HogTransformerService | null,
    prePluginsEvent: PluginEvent,
    postPluginsEvent: PluginEvent | null,
    samplePercentage?: number
): Promise<void> {
    if (!hogTransformer) {
        return
    }

    if (!samplePercentage || Math.random() > samplePercentage) {
        return
    }

    try {
        // TRICKY: We really want to make sure that the other event is unaffected
        const clonedEvent = cloneObject(prePluginsEvent)
        const result = await hogTransformer.transformEvent(clonedEvent)
        const hogEvent = result.event

        if (!hogEvent || !postPluginsEvent) {
            if (!hogEvent && !postPluginsEvent) {
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

        const diff = compareEvents(postPluginsEvent, hogEvent)
        if (diff) {
            status.warn('⚠️', 'Hog transformation produced an event but the plugin did not', {
                team_id: prePluginsEvent.team_id,
                diff,
            })
            counterHogTransformationDiff.inc({ outcome: 'diff' })
        } else {
            counterHogTransformationDiff.inc({ outcome: 'same' })
        }
    } catch (error) {
        status.error('Error occured when comparing plugin event to hog transform', error)
    }
}
