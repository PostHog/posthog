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

// Create a deep copy of the event to modify
let returnEvent := jsonParse(jsonStringify(event))

// Helper function to get nested property value
fun getNestedValue(obj, path) {
    let parts := splitByString('.', path)
    let current := obj
    
    for (let part in parts) {
        if (current = null) {
            return null
        }
        current := current[part]
    }
    return current
}

// Helper function to set nested property value
fun setNestedValue(obj, path, value) {
    let parts := splitByString('.', path)
    let current := obj
    
    // Navigate to the parent object of the target property
    for (let i := 1; i < length(parts); i := i + 1) {
        let part := parts[i]
        if (current[part] = null) {
            current[part] := {}
        }
        current := current[part]
    }
    
    // Set the value on the last part
    let lastPart := parts[length(parts)]
    current[lastPart] := value
}

// Hash each property value
for (let _, path in propertiesToHash) {
    let value := getNestedValue(event.properties, path)
    if (notEmpty(value)) {
        let hashedValue := sha256Hex(toString(value))
        setNestedValue(returnEvent.properties, path, hashedValue)
    }
}

return returnEvent
`,
    inputs_schema: [
        {
            key: 'propertiesToHash',
            type: 'dictionary',
            label: 'Properties to Hash',
            description: 'Add property paths to hash (use dot notation for nested properties, e.g. "$set.$email")',
            default: {
                Ip: '$ip',
            },
            secret: false,
            required: true,
        },
    ],
}
