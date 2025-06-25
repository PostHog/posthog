import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'beta',
    type: 'transformation',
    id: 'template-hash-properties',
    name: 'Hash properties',
    description:
        'Hashes sensitive fields with SHA256 using a salt. This helps protect user privacy while maintaining data consistency.',
    icon_url: '/static/hedgehog/police-hog.png',
    category: ['Custom'],
    hog: `
// Function to hash a value with SHA256
fun hashValue(value, salt) {
    if (empty(value) or typeof(value) != 'string') {
        return value
    }
    
    // Create hash using SHA256
    let hash := sha256Hex(concat(value, salt))
    return hash
}

// Create a copy of the event to modify
let anonymizedEvent := event

// Split private fields by comma and process each one
let fieldNames := splitByString(',', inputs.privateFields)
for (let fieldName in fieldNames) {
    let trimmedFieldName := trim(fieldName)
    if (not empty(trimmedFieldName)) {
        // Check if field exists in event properties
        if (not empty(event.properties?.[trimmedFieldName])) {
            anonymizedEvent.properties[trimmedFieldName] := hashValue(event.properties[trimmedFieldName], inputs.salt)
        }
        
        // Check if field exists at event level (like distinct_id)
        if (not empty(event[trimmedFieldName])) {
            anonymizedEvent[trimmedFieldName] := hashValue(event[trimmedFieldName], inputs.salt)
        }

        if (inputs.includeSetProperties) {
            if (not empty(event.properties?.$set?.[trimmedFieldName])) {
                anonymizedEvent.properties.$set[trimmedFieldName] := hashValue(event.properties.$set[trimmedFieldName], inputs.salt)
            }

            if (not empty(event.properties?.$set_once?.[trimmedFieldName])) {
                anonymizedEvent.properties.$set_once[trimmedFieldName] := hashValue(event.properties.$set_once[trimmedFieldName], inputs.salt)
            }
        }
    }
}

return anonymizedEvent
    `,
    inputs_schema: [
        {
            key: 'salt',
            type: 'string',
            label: 'Salt',
            description: 'A secret salt used for hashing. This should be kept secure and consistent.',
            default: '',
            secret: true,
            required: true,
        },
        {
            key: 'privateFields',
            type: 'string',
            label: 'Fields to hash',
            description:
                'Comma-separated list of field names to hash. Can include both event properties and top-level event fields like distinct_id.',
            default: 'distinct_id,name,userid,email',
            secret: false,
            required: true,
        },
        {
            key: 'includeSetProperties',
            type: 'boolean',
            label: 'Also hash $set and $set_once properties',
            description:
                'Whether to also hash $set and $set_once properties that are used to update Person properties.',
            default: true,
            secret: false,
            required: false,
        },
    ],
}
