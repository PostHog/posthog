import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation_log',
    id: 'template-log-transformation-redact-attributes',
    name: 'Hash log attributes',
    description: 'Replace the values of the configured log attributes with a SHA-256 hash to protect PII.',
    icon_url: '/static/hedgehog/builder-hog-02.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
let r := record
for (let _, key in splitByString(',', inputs.attributeKeys)) {
    let k := trim(key)
    if (notEmpty(k) and notEmpty(r.attributes[k])) {
        r.attributes[k] := sha256Hex(r.attributes[k])
    }
}
return r
`,
    inputs_schema: [
        {
            key: 'attributeKeys',
            type: 'string',
            label: 'Attribute keys to hash',
            description: 'Comma-separated attribute keys whose values are replaced with a SHA-256 hash.',
            default: 'user.email,user.id',
            secret: false,
            required: true,
        },
    ],
}
