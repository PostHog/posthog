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

fun remapIn(properties, propertyName) {
    if (not empty(properties)) {
        if (has(keys(properties), propertyName)) {
            properties[propertyName] := remapValue(properties[propertyName])
        }
    }
    return null
}

for (let propertyName in splitByString(',', inputs.propertyNames)) {
    propertyName := trim(propertyName)
    if (not empty(propertyName)) {
        remapIn(returnEvent.properties, propertyName)
        remapIn(returnEvent.properties.$set, propertyName)
        remapIn(returnEvent.properties.$set_once, propertyName)
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
                'Comma-separated list of event properties to remap, for example "plan, region". Person properties set on the event ($set and $set_once) are remapped too.',
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
