import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation',
    id: 'template-url-parameters-to-properties',
    name: 'URL parameters to event properties',
    description: 'Copies chosen query parameters from $current_url into event properties.',
    icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(event.properties?.$current_url) or typeof(event.properties.$current_url) != 'string') {
    return event
}

let returnEvent := event
let parts := splitByString('?', event.properties.$current_url, 2)
if (length(parts) < 2) {
    return event
}

// Drop a trailing hash fragment so it is not read as part of the last value.
let queryString := splitByString('#', parts[2], 2)[1]
let pairs := splitByString('&', queryString)

for (let raw in splitByString(',', inputs.parameters)) {
    let name := trim(raw)
    if (not empty(name)) {
        let values := []
        for (let pair in pairs) {
            if (not empty(pair)) {
                let kv := splitByString('=', pair, 2)
                let matches := inputs.ignoreCase ? (lower(kv[1]) == lower(name)) : (kv[1] == name)
                if (matches) {
                    values := arrayPushBack(values, length(kv) > 1 ? decodeURLComponent(kv[2]) : '')
                }
            }
        }
        if (length(values) > 0) {
            let key := concat(inputs.prefix, name, inputs.suffix)
            let storeValue := (length(values) == 1 and not inputs.alwaysJson) ? values[1] : jsonStringify(values)
            returnEvent.properties[key] := storeValue
            if (inputs.setAsUserProperties) {
                if (empty(returnEvent.properties.$set)) {
                    returnEvent.properties.$set := {}
                }
                returnEvent.properties.$set[key] := storeValue
            }
            if (inputs.setAsInitialUserProperties) {
                if (empty(returnEvent.properties.$set_once)) {
                    returnEvent.properties.$set_once := {}
                }
                returnEvent.properties.$set_once[concat('initial_', key)] := storeValue
            }
        }
    }
}

return returnEvent
    `,
    inputs_schema: [
        {
            key: 'parameters',
            type: 'string',
            label: 'Query parameters',
            description: 'Comma-separated query parameter names to copy into event properties.',
            default: '',
            required: true,
        },
        {
            key: 'prefix',
            type: 'string',
            label: 'Property name prefix',
            description: 'Text placed before each parameter name when naming the property.',
            default: '',
            required: false,
        },
        {
            key: 'suffix',
            type: 'string',
            label: 'Property name suffix',
            description: 'Text placed after each parameter name when naming the property.',
            default: '',
            required: false,
        },
        {
            key: 'ignoreCase',
            type: 'boolean',
            label: 'Ignore case',
            description: 'Match parameter names without regard to upper or lower case.',
            default: false,
            required: false,
        },
        {
            key: 'alwaysJson',
            type: 'boolean',
            label: 'Always store as JSON',
            description: 'Store every value as a JSON array, even when a parameter appears once.',
            default: false,
            required: false,
        },
        {
            key: 'setAsUserProperties',
            type: 'boolean',
            label: 'Also set as user properties',
            description: 'Copy each value into $set so it updates the person.',
            default: false,
            required: false,
        },
        {
            key: 'setAsInitialUserProperties',
            type: 'boolean',
            label: 'Also set as initial user properties',
            description: 'Copy each value into $set_once as initial_<name> so it is set only once per person.',
            default: false,
            required: false,
        },
    ],
}
