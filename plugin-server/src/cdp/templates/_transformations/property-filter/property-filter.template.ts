import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'transformation',
    id: 'template-property-filter',
    name: 'Property Filter',
    description:
        'This transformation removes properties from event object and nested properties from event.properties.',
    icon_url: '/static/hedgehog/builder-hog-02.png',
    category: ['Custom'],
    hog: `
// Get the properties to filter from inputs and split by comma
let propertiesToFilter := []
if (notEmpty(inputs.propertiesToFilter)) {
    propertiesToFilter := splitByString(',', inputs.propertiesToFilter)
}

if (empty(propertiesToFilter)) {
    return event
}

// Helper function to split path into parts
fun splitPath(path) {
    return splitByString('.', trim(path))
}

// Helper function to check if a path matches the start of another path
fun pathStartsWith(path, prefix) {
    let pathParts := splitPath(path)
    let prefixParts := splitPath(prefix)
    
    if (length(prefixParts) > length(pathParts)) {
        return false
    }
    
    for (let i := 1; i <= length(prefixParts); i := i + 1) {
        if (trim(pathParts[i]) != trim(prefixParts[i])) {
            return false
        }
    }
    
    return true
}

// Helper function to get remaining path
fun getRemainingPath(path, prefix) {
    let pathParts := splitPath(path)
    let prefixParts := splitPath(prefix)
    let result := ''
    
    for (let i := length(prefixParts) + 1; i <= length(pathParts); i := i + 1) {
        if (notEmpty(result)) {
            result := concat(result, '.')
        }
        result := concat(result, pathParts[i])
    }
    
    return result
}

// Helper function to filter properties from an object
fun filterObject(obj, propertiesToRemove, currentPath) {
    if (obj = null) {
        return null
    }
    
    if (typeof(obj) != 'object') {
        return obj
    }
    
    let result := {}
    let objKeys := keys(obj)
    
    for (let key in objKeys) {
        let shouldKeep := true
        let fullPath := if(notEmpty(currentPath), concat(currentPath, '.', key), key)
        
        for (let propToFilter in propertiesToRemove) {
            if (lower(trim(fullPath)) = lower(trim(propToFilter))) {
                shouldKeep := false
            }
        }
        
        if (shouldKeep) {
            let value := obj[key]
            if (typeof(value) = 'object' and value != null) {
                result[key] := filterObject(value, propertiesToRemove, fullPath)
            } else {
                result[key] := value
            }
        }
    }
    
    return result
}

// Create a copy of the event
let returnEvent := {}

// Copy non-filtered top-level properties
let eventKeys := keys(event)
for (let key in eventKeys) {
    let shouldKeep := true
    for (let propToFilter in propertiesToFilter) {
        if (position(propToFilter, '.') = 0 and trim(key) = trim(propToFilter)) {
            shouldKeep := false
        }
    }
    
    if (shouldKeep) {
        if (key = 'properties' and notEmpty(event.properties)) {
            returnEvent.properties := filterObject(event.properties, propertiesToFilter, '')
        } else {
            returnEvent[key] := event[key]
        }
    }
}

return returnEvent
`,
    inputs_schema: [
        {
            key: 'propertiesToFilter',
            type: 'string',
            label: 'Properties to Filter',
            description:
                'Comma-separated list of properties to filter. For top-level properties use the property name (e.g. "distinct_id"), for nested properties use the full path (e.g. "user.profile.settings.api_key")',
            default: '$ip',
            secret: false,
            required: true,
        },
    ],
}
