import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation',
    id: 'template-remap-property-values',
    name: 'Remap property values',
    description:
        'Replace one property value with another, so a value you renamed shows as a single value in filters and breakdowns. Only applies to new events.',
    icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(event.properties)) {
    return event
}

fun remapValue(value) {
    if (value == null) {
        return value
    }
    let key := toString(value)
    if (has(keys(inputs.valueMapping), key)) {
        return inputs.valueMapping[key]
    }
    return value
}

let returnEvent := event

fun remapIn(properties, key) {
    if (not empty(properties)) {
        if (has(keys(properties), key)) {
            properties[key] := remapValue(properties[key])
        }
    }
    return null
}

// Walk a dot path like '$set.plan' down to the object holding the last key
fun resolveParent(properties, parts) {
    let current := properties
    let i := 1
    while (i < length(parts)) {
        if (empty(current)) {
            return null
        }
        if (not has(keys(current), parts[i])) {
            return null
        }
        current := current[parts[i]]
        i := i + 1
    }
    return current
}

for (let propertyPath in splitByString(',', inputs.propertyNames)) {
    propertyPath := trim(propertyPath)
    if (not empty(propertyPath)) {
        let parts := splitByString('.', propertyPath)
        let key := parts[length(parts)]
        remapIn(resolveParent(returnEvent.properties, parts), key)
        if (length(parts) == 1) {
            remapIn(returnEvent.properties.$set, key)
            remapIn(returnEvent.properties.$set_once, key)
        }
    }
}

return returnEvent
    `,
    inputs_schema: [
        {
            key: 'propertyNames',
            type: 'string',
            label: 'Properties to remap',
            description:
                'Comma-separated list of event properties to remap, for example "plan, region". A name on its own also remaps the person properties the event sets. Use a dot path such as "$set.plan" to remap one nested property.',
            required: true,
        },
        {
            key: 'valueMapping',
            type: 'dictionary',
            label: 'Value mapping',
            templating: false,
            default: {},
            description:
                'The old value is the key and the new value is what replaces it, for example key "grp_a1" with value "grp_b2". Values that are not listed stay as they are.',
            required: true,
        },
    ],
}
