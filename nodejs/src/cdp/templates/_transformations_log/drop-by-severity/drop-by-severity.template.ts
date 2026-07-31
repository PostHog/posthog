import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation_log',
    id: 'template-log-transformation-drop-by-severity',
    name: 'Drop logs by severity',
    description: 'Drop noisy log records at the configured severity levels (for example debug and trace).',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// severity_text is lowercased upstream, so normalise the configured list too.
let drop := splitByString(',', lower(inputs.severitiesToDrop))
for (let _, s in drop) {
    if (record.severity_text == trim(s)) {
        return null
    }
}
return record
`,
    inputs_schema: [
        {
            key: 'severitiesToDrop',
            type: 'string',
            label: 'Severities to drop',
            description: 'Comma-separated severity levels to drop, e.g. "debug,trace". Case-insensitive.',
            default: 'debug,trace',
            secret: false,
            required: true,
        },
    ],
}
