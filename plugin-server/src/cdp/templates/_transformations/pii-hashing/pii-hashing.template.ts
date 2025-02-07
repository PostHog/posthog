import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'transformation',
    id: 'template-pii-hashing',
    name: 'PII Data Hashing',
    description:
        'This transformation hashes sensitive personal data (PII) like email, phone numbers, etc. using SHA-256 to protect user privacy.',
    icon_url: '/static/hedgehog/builder-hog-02.png',
    category: ['Custom'],
    hog: `
// Get the properties to hash from inputs
let propertiesToHash := inputs.propertiesToHash
if (empty(propertiesToHash)) {
    return event
}

// Create a copy of the event to modify
let returnEvent := event

// Hash each property value
for (let propName, path in propertiesToHash) {
    let value := path
    if (notEmpty(value) and value != propName) {  // Check if path resolved to a value
        returnEvent.properties[propName] := sha256Hex(toString(value))
    }
}

return returnEvent
`,
    inputs_schema: [
        {
            key: 'propertiesToHash',
            type: 'dictionary',
            label: 'Properties to Hash',
            description: 'Add property names to hash (e.g., "$email", "$ip", "$device_type").',
            default: {
                $email: '{event.properties.$email}',
                $ip: '{event.properties.$ip}',
            },
            secret: false,
            required: true,
        },
    ],
}
