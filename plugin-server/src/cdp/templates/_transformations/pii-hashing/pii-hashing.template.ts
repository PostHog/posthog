import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'beta',
    type: 'transformation',
    id: 'template-pii-hashing',
    name: 'PII Data Hashing',
    description:
        'This transformation hashes sensitive personal data (PII) like email, phone numbers, etc. using SHA-256 to protect user privacy.',
    icon_url: '/static/hedgehog/builder-hog-02.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// Get the properties to hash from inputs and split by comma
let propertiesToHash := []
if (notEmpty(inputs.propertiesToHash)) {
    propertiesToHash := splitByString(',', inputs.propertiesToHash)
}
let hashDistinctId := inputs.hashDistinctId
let salt := inputs.salt

if (empty(propertiesToHash) and not hashDistinctId) {
    return event
}

// Create a deep copy of the event to modify
let returnEvent := event

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

// Hash distinct_id if enabled also potentially using a salt
if (hashDistinctId and notEmpty(event.distinct_id)) {
    if(notEmpty(salt)) {
        returnEvent.distinct_id := sha256Hex(concat(toString(event.distinct_id), salt))
    } else {
        returnEvent.distinct_id := sha256Hex(toString(event.distinct_id))
    }
}

// Hash each property value potentially using a salt
for (let _, path in propertiesToHash) {
    let value := getNestedValue(event.properties, trim(path))  // Trim to handle spaces after commas
    if (notEmpty(value)) {
        if(notEmpty(salt)) {
            let hashedValue := sha256Hex(concat(toString(value), salt))
            setNestedValue(returnEvent.properties, trim(path), hashedValue)
        } else {
            let hashedValue := sha256Hex(toString(value))
            setNestedValue(returnEvent.properties, trim(path), hashedValue)
        }
    }
}

return returnEvent
`,
    inputs_schema: [
        {
            key: 'propertiesToHash',
            type: 'string',
            label: 'Properties to Hash',
            description: 'Comma-separated list of property paths to hash (e.g. "$ip,$email,$set.$phone")',
            default: '$ip',
            secret: false,
            required: true,
        },
        {
            key: 'hashDistinctId',
            type: 'boolean',
            label: 'Hash Distinct ID',
            description: 'Whether to hash the distinct_id field',
            default: false,
            secret: false,
            required: false,
        },
        {
            key: 'salt',
            type: 'string',
            label: 'Salt',
            description: 'Optional salt to add to the hashed values for additional security',
            default: '',
            secret: true,
            required: false,
        },
    ],
}
