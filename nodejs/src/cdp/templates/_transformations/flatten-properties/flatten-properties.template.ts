import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation',
    id: 'template-flatten-properties',
    name: 'Flatten Properties',
    description:
        'Flattens nested event properties into top-level keys joined by a separator, for example a.b.c becomes a__b__c.',
    icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// These events create very large numbers of flattened properties, so they are skipped.
if (event.event == '$autocapture' or event.event == 'organization usage report') {
    return event
}
if (empty(event.properties)) {
    return event
}

let sep := inputs.separator
// Internal properties used in event processing are left nested.
let denyList := ['$elements', '$elements_chain', '$groups', '$active_feature_flags', '$heatmap_data', '$web_vitals_data']

fun isContainer(v) {
    return v != null and (typeof(v) == 'object' or typeof(v) == 'array')
}

// Write the flattened leaf paths of \`obj\` into \`out\`, joining keys with the separator.
// Every nested step adds the separator, also when the parent key is an empty string. Without
// that, a property named '' would emit its children as unprefixed top-level keys and overwrite
// the properties that already use those names.
fun flattenInto(out, obj, prefix, sep) {
    for (let key, value in obj) {
        let path := concat(prefix, sep, toString(key))
        if (isContainer(value)) {
            flattenInto(out, value, path, sep)
        } else {
            out[path] := value
        }
    }
    return out
}

let returnEvent := event
let props := event.properties

// Flatten nested containers (skipping internal keys and the $set family) into new top-level keys.
let flat := {}
for (let key, value in props) {
    if (not has(denyList, key) and key != '$set' and key != '$set_once' and key != '$group_set') {
        if (isContainer(value)) {
            flattenInto(flat, value, key, sep)
        }
    }
}
for (let flatKey, flatValue in flat) {
    returnEvent.properties[flatKey] := flatValue
}

// $set, $set_once and $group_set keep their own keys and gain flattened leaves under a fresh prefix.
for (let special in ['$set', '$set_once', '$group_set']) {
    let sub := props[special]
    if (sub != null and typeof(sub) == 'object') {
        let subFlat := {}
        for (let key, value in sub) {
            if (isContainer(value)) {
                flattenInto(subFlat, value, key, sep)
            }
        }
        for (let flatKey, flatValue in subFlat) {
            returnEvent.properties[special][flatKey] := flatValue
        }
    }
}

return returnEvent
    `,
    inputs_schema: [
        {
            key: 'separator',
            type: 'string',
            label: 'Separator',
            description: 'The string used to join nested keys, for example __ turns a.b into a__b.',
            default: '__',
            required: true,
        },
    ],
}
