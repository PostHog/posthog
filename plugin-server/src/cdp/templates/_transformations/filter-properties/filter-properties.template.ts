import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'transformation',
    id: 'template-filter-properties',
    name: 'Filter Properties',
    description: 'Filter out specific properties from the event by setting them to null or removing them completely.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// Check if the event has properties
if (empty(event.properties)) {
    return event
}

let returnEvent := event
let propertiesToFilter := splitByString(',', inputs.propertiesToFilter)

// Process each property to filter
let i := 1
while (i <= length(propertiesToFilter)) {
    let prop := trim(propertiesToFilter[i])
    if (not empty(prop)) {
        let parts := splitByString('.', prop)
        let current := returnEvent.properties
        let found := true
        
        // Navigate to the parent object
        let j := 1
        while (j < length(parts) and found) {
            if (not has(keys(current), parts[j])) {
                found := false
            } else {
                current := current[parts[j]]
            }
            j := j + 1
        }
        
        // Handle the last part if we found the parent object
        if (found and j == length(parts)) {
            let lastPart := parts[length(parts)]
            if (has(keys(current), lastPart)) {
                current[lastPart] := null 
            }
        }
    }
    i := i + 1
}

return returnEvent
    `,
    inputs_schema: [
        {
            key: 'propertiesToFilter',
            type: 'string',
            label: 'Properties to filter',
            description: 'Comma-separated list of properties to filter (e.g. "$set.email, $set.name, custom_prop")',
            required: true,
        },
    ],
}
