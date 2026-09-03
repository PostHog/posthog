import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation',
    id: 'template-downsampling',
    name: 'Downsampling',
    description:
        'Keeps only a percentage of events to reduce volume. Stable sampling keeps the same distinct IDs as the percentage grows; random sampling decides per event.',
    icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// Only sample the events named here; empty means sample every event.
let applies := true
if (not empty(trim(inputs.triggeringEvents))) {
    applies := false
    for (let name in splitByString(',', inputs.triggeringEvents)) {
        if (trim(name) == event.event) {
            applies := true
        }
    }
}

if (not applies) {
    return event
}

let keep := true
if (inputs.randomSampling) {
    keep := (randomFloat() * 100) <= inputs.percentage
} else {
    // Map the distinct ID to a stable value in [0, 1] from its sha256 hash. A distinct ID kept
    // at a lower percentage stays kept as the percentage grows.
    let hex := sha256Hex(event.distinct_id)
    let digits := '0123456789abcdef'
    let acc := 0.0
    let maxAcc := 0.0
    let i := 1
    while (i <= 13) {
        let d := position(digits, substring(hex, i, 1)) - 1
        if (d < 0) {
            d := 0
        }
        acc := acc * 16 + d
        maxAcc := maxAcc * 16 + 15
        i := i + 1
    }
    keep := (acc / maxAcc) <= (inputs.percentage / 100)
}

if (keep) {
    return event
}
return null
    `,
    inputs_schema: [
        {
            key: 'percentage',
            type: 'number',
            label: 'Percentage of events to keep',
            description: 'A number between 0 and 100. 100 keeps every event, 0 drops every event.',
            default: 100,
            required: true,
        },
        {
            key: 'randomSampling',
            type: 'boolean',
            label: 'Use random sampling',
            description:
                'When off, sampling is stable per distinct ID, so raising the percentage only adds events. When on, each event is decided independently.',
            default: false,
            required: false,
        },
        {
            key: 'triggeringEvents',
            type: 'string',
            label: 'Events to sample',
            description: 'Comma-separated event names to sample. Leave empty to sample every event.',
            default: '',
            required: false,
        },
    ],
}
