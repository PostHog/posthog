import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation_log',
    id: 'template-log-transformation-pii-scrub',
    name: 'Scrub PII from log bodies',
    description: 'Redact emails, API keys, and bearer tokens from the log body using regular expressions.',
    icon_url: '/static/hedgehog/builder-hog-02.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
let r := record
if (r.body == null) {
    return r
}

// Character classes ([.] [ ]) keep these readable — no backslash escaping needed.
// Non-capturing groups (?:...) so the whole match is redacted, not a sub-group.
let patterns := [
    '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}',
    '(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{8,}',
    '[Bb]earer[ ]+[A-Za-z0-9._-]{10,}'
]

for (let _, pattern in patterns) {
    let found := extractRegex(r.body, pattern)
    // Each replaceAll clears one distinct match; guard caps work per record.
    let guard := 0
    while (notEmpty(found) and guard < 100) {
        r.body := replaceAll(r.body, found, inputs.replacement)
        found := extractRegex(r.body, pattern)
        guard := guard + 1
    }
}

return r
`,
    inputs_schema: [
        {
            key: 'replacement',
            type: 'string',
            label: 'Replacement text',
            description: 'Replaces each matched value in the log body.',
            default: '[REDACTED]',
            secret: false,
            required: true,
        },
    ],
}
