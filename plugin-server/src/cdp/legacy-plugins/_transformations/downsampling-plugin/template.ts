import { HogFunctionTemplate } from '../../../templates/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-downsampling-plugin',
    name: 'Downsample',
    description: 'Reduces event volume coming into PostHog',
    icon_url: 'https://raw.githubusercontent.com/posthog/downsampling-plugin/main/logo.png',
    category: ['Custom'],
    hog: `return event`,
    inputs_schema: [
        {
            type: 'string',
            key: 'percentage',
            label: '% of events to keep',
            default: '100',
            required: false,
        },
        {
            type: 'choice',
            key: 'samplingMethod',
            label: 'Sampling method',
            choices: [
                { value: 'Random sampling', label: 'Random sampling' },
                { value: 'Distinct ID aware sampling', label: 'Distinct ID aware sampling' },
            ],
            default: 'Distinct ID aware sampling',
            required: false,
        },
    ],
}
