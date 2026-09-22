import { PluginEvent } from '~/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

/**
 * Some events will always create very large numbers of flattened properties
 * This is undesirable since a large enough number of properties for a particular team can slow down the property filter in the UI
 * If the problem property has a unique enough name it can be added to the propertyDenyList
 * If not (or if many properties for a given event are problematic) then the event can be added here
 */
const eventDenyList = ['$autocapture', 'organization usage report']

export function processEvent(event: PluginEvent, { config }: LegacyTransformationPluginMeta) {
    try {
        if (!eventDenyList.includes(event.event) && event.properties) {
            event.properties = flattenProperties(event.properties, config.separator)
        }
    } catch (e) {
        throw e
    }
    return event
}

const propertyDenyList = [
    '$elements',
    '$elements_chain',
    '$groups',
    '$active_feature_flags',
    '$heatmap_data',
    '$web_vitals_data',
]

const flattenProperties = (props: Record<string, any>, sep: string, nestedChain: string[] = []) => {
    // Accumulate with Object.assign: spreading the accumulator per key is O(N^2) in the
    // number of properties, and this runs synchronously on the ingestion consumer.
    const newProps: Record<string, any> = {}
    for (const [key, value] of Object.entries(props)) {
        if (propertyDenyList.includes(key)) {
            // Hide 'internal' properties used in event processing
        } else if (key === '$set' || key === '$set_once' || key === '$group_set') {
            newProps[key] = { ...props[key], ...flattenProperties(props[key], sep) }
        } else if (Array.isArray(value)) {
            Object.assign(newProps, flattenProperties(props[key], sep, [...nestedChain, key]))
        } else if (value !== null && typeof value === 'object' && Object.keys(value).length > 0) {
            Object.assign(newProps, flattenProperties(props[key], sep, [...nestedChain, key]))
        } else {
            if (nestedChain.length > 0) {
                newProps[nestedChain.join(sep) + `${sep}${key}`] = value
            }
        }
    }
    if (nestedChain.length > 0) {
        return newProps
    }
    return { ...props, ...newProps }
}
