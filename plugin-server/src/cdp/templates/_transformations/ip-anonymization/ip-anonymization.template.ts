import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'transformation',
    id: 'template-ip-anonymization',
    name: 'IP Anonymization',
    description:
        'This transformation sets the last octet of an IP address to zero (e.g., 12.214.31.144 → 12.214.31.0), protecting user privacy and reducing disclosure risk.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `
// Check if the event has an IP address
if (empty(event.properties?.$ip)) {
    print('No IP address found in event')
    return event
}

let ip := event.properties.$ip
let parts := splitByString('.', ip)

// Check if we have a valid IPv4 address
if (length(parts) = 4) {
    // Replace the last octet with '0'
    let anonymizedIp := concat(
        parts[1], 
        '.', 
        parts[2], 
        '.', 
        parts[3], 
        '.0'
    )
    
    let returnEvent := event
    returnEvent.properties.$ip := anonymizedIp
    return returnEvent
}

// If we don't have a valid IPv4, return original event
return event
    `,
    inputs_schema: [],
}
