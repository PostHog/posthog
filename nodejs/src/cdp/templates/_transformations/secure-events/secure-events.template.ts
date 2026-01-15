import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'beta',
    type: 'transformation',
    id: 'template-secure-events',
    name: 'Secure event validation',
    description:
        'Validates events using a shared secret to verify distinct_id authenticity. Events can be marked as verified or dropped if validation fails.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// Set up return event with default unverified status
let returnEvent := event
if (not returnEvent.properties) {
    returnEvent.properties := {}
}
returnEvent.properties['$verified_distinct_id'] := false

// Check if distinct_id exists
if (empty(event.distinct_id)) {
    if (inputs.enforceSecureMode) {
        return null
    }
    return returnEvent
}

// Get the hash from properties
let providedHash := event.properties['$distinct_id_hash']
if (empty(providedHash)) {
    providedHash := event.properties['distinct_id_hash']
}

// Check if hash exists
if (empty(providedHash)) {
    if (inputs.enforceSecureMode) {
        return null
    }
    return returnEvent
}

let isValid := false

// Validate against primary secret
if (notEmpty(inputs.primarySecret)) {
    let expectedHash := sha256HmacChainHex([inputs.primarySecret, toString(event.distinct_id)])
    if (expectedHash == providedHash) {
        isValid := true
    }
}

// If primary fails, try secondary secret for key rotation support
if (not isValid and notEmpty(inputs.secondarySecret)) {
    let expectedHash := sha256HmacChainHex([inputs.secondarySecret, toString(event.distinct_id)])
    if (expectedHash == providedHash) {
        isValid := true
    }
}

// Handle validation result
if (not isValid and inputs.enforceSecureMode) {
    return null
}

// Update verification status and return
returnEvent.properties['$verified_distinct_id'] := isValid
return returnEvent
`,
    inputs_schema: [
        {
            key: 'primarySecret',
            type: 'string',
            label: 'Primary shared secret',
            description: 'The primary shared secret used to generate and verify HMAC-SHA256 hashes of the distinct_id',
            default: '',
            secret: true,
            required: true,
        },
        {
            key: 'secondarySecret',
            type: 'string',
            label: 'Secondary shared secret',
            description:
                'Optional secondary shared secret for key rotation. Events signed with either primary or secondary secret will be accepted.',
            default: '',
            secret: true,
            required: false,
        },
        {
            key: 'enforceSecureMode',
            type: 'boolean',
            label: 'Enforce secure mode',
            description:
                'When enabled, events that fail validation will be dropped entirely. When disabled, events will be marked with $verified_distinct_id property (true/false) but not dropped.',
            default: false,
            secret: false,
            required: false,
        },
    ],
}
