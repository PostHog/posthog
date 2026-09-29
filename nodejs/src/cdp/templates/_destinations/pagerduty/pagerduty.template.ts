import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'beta',
    type: 'destination',
    id: 'template-pagerduty',
    name: 'PagerDuty',
    description: 'Triggers, acknowledges or resolves a PagerDuty incident',
    icon_url: '/static/services/pagerduty.png',
    category: ['Monitoring & Alerts'],
    code_language: 'hog',
    code: `
let action := inputs.event_action
if (not has(['trigger', 'acknowledge', 'resolve'], action)) {
    throw Error(f'Unsupported event action "{action}". Use trigger, acknowledge or resolve.')
}

let body := {
    'routing_key': inputs.routing_key,
    'event_action': action
}

if (notEmpty(inputs.dedup_key)) {
    body['dedup_key'] := inputs.dedup_key
}

if (action == 'trigger') {
    let severity := inputs.severity
    if (not has(['critical', 'error', 'warning', 'info'], severity)) {
        severity := 'error'
    }

    // PagerDuty answers a blank payload.source with a 400 that names the field, which reads as a
    // configuration mistake. The default value ends at project.name, which is empty when the team
    // row carries no name, so a correctly configured destination can still send nothing.
    let source := inputs.source
    if (empty(source)) {
        source := 'PostHog'
    }

    let payload := {
        'summary': substring(inputs.summary, 1, 1024),
        'source': source,
        'severity': severity
    }
    if (notEmpty(inputs.component)) {
        payload['component'] := inputs.component
    }
    if (notEmpty(inputs.event_class)) {
        payload['class'] := inputs.event_class
    }
    if (notEmpty(inputs.custom_details)) {
        payload['custom_details'] := inputs.custom_details
    }

    body['payload'] := payload
    body['client'] := 'PostHog'
    if (notEmpty(inputs.links)) {
        body['links'] := inputs.links
    }
} else if (empty(inputs.dedup_key)) {
    throw Error(f'A dedup key is required to {action} an incident.')
}

let res := fetch('https://events.pagerduty.com/v2/enqueue', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json'
    },
    'body': body
})

if (res.status < 200 or res.status >= 300) {
    throw Error(f'PagerDuty rejected the event: {res.status}: {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'routing_key',
            type: 'string',
            label: 'Routing key',
            description: 'The Events API v2 integration key from your PagerDuty service.',
            secret: true,
            required: true,
        },
        {
            key: 'event_action',
            type: 'choice',
            label: 'Event action',
            description:
                'Trigger opens an incident. Acknowledge and resolve update the incident with the same dedup key.',
            choices: [
                { label: 'Trigger', value: 'trigger' },
                { label: 'Acknowledge', value: 'acknowledge' },
                { label: 'Resolve', value: 'resolve' },
            ],
            default: 'trigger',
            secret: false,
            required: true,
        },
        {
            key: 'dedup_key',
            type: 'string',
            label: 'Dedup key',
            description:
                'Events with the same key update one incident. Acknowledge and resolve need it. If you leave it empty, PagerDuty opens a new incident for each trigger.',
            default: '',
            secret: false,
            required: false,
        },
        {
            key: 'summary',
            type: 'string',
            label: 'Summary',
            description: 'The incident title. PagerDuty keeps the first 1024 characters.',
            default: '{event.event} by {person.name}',
            secret: false,
            required: true,
        },
        {
            key: 'source',
            type: 'string',
            label: 'Source',
            description: 'The system that has the problem.',
            default: '{event.properties.source ?? project.name}',
            secret: false,
            required: true,
        },
        {
            key: 'severity',
            type: 'choice',
            label: 'Severity',
            description: 'Any other value is sent as error.',
            choices: [
                { label: 'Critical', value: 'critical' },
                { label: 'Error', value: 'error' },
                { label: 'Warning', value: 'warning' },
                { label: 'Info', value: 'info' },
            ],
            default: 'error',
            secret: false,
            required: true,
        },
        {
            key: 'component',
            type: 'string',
            label: 'Component',
            description: 'The part of the source system that has the problem.',
            default: '',
            secret: false,
            required: false,
        },
        {
            key: 'event_class',
            type: 'string',
            label: 'Class',
            description: 'The type of the event, for example firing.',
            default: '',
            secret: false,
            required: false,
        },
        {
            key: 'custom_details',
            type: 'json',
            label: 'Custom details',
            description: 'Extra data that PagerDuty shows on the incident and can use in event rules.',
            default: { event: '{event}', person: '{person}' },
            secret: false,
            required: false,
        },
        {
            key: 'links',
            type: 'json',
            label: 'Links',
            description: 'A list of links with href and text that PagerDuty shows on the incident.',
            default: [{ href: '{event.url}', text: 'View event in PostHog' }],
            secret: false,
            required: false,
        },
    ],
}
