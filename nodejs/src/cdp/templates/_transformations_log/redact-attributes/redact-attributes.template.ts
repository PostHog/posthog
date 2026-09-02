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
let salt := inputs.salt
if (salt == null) {
    salt := ''
}
let r := record
for (let _, key in splitByString(',', inputs.attributeKeys)) {
    let k := trim(key)
    if (notEmpty(k) and notEmpty(r.attributes[k])) {
        r.attributes[k] := sha256Hex(concat(salt, r.attributes[k]))
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
        {
            key: 'salt',
            type: 'string',
            label: 'Salt',
            description:
                'Prepended to the value before hashing. Strongly recommended: without a salt, hashes of low-entropy values like emails can be reversed by lookup tables.',
            secret: true,
            required: false,
        },
    ],
}
