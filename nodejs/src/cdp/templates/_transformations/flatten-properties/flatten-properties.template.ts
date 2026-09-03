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

// The flatten runs as a host function so it stays linear in the property count. Doing it in hog
// is quadratic, because the VM re-costs a local on every read, and can hit the time budget.
let returnEvent := event
returnEvent.properties := flattenProperties(event.properties, inputs.separator)
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
