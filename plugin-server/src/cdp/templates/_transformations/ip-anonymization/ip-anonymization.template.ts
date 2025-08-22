import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'beta',
    type: 'transformation',
    id: 'template-ip-anonymization',
    name: 'IP Anonymization',
    description:
        'This transformation sets the last octet of an IP address to zero (e.g., 12.214.31.144 → 12.214.31.0), protecting user privacy and reducing disclosure risk.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// Check if the event has an IP address
if (empty(event.properties?.$ip)) {
    print('No IP address found in event')
    return event
}

let ip := event.properties.$ip
let parts := splitByString('.', ip)

// Check if we have exactly 4 parts for IPv4
if (length(parts) != 4) {
    print('Invalid IP address format: wrong number of octets')
    return event
}

// Validate each octet is a number between 0 and 255
for (let i := 1; i <= 4; i := i + 1) {
    let octet := toInt(parts[i])
    if (octet = null or octet < 0 or octet > 255) {
        print('Invalid IP address: octets must be numbers between 0 and 255')
        return event
    }
}

// Replace the last octet with '0'
let anonymizedIp := concat(parts[1], '.', parts[2], '.', parts[3], '.0')
    
let returnEvent := event
returnEvent.properties.$ip := anonymizedIp
return returnEvent
    `,
    inputs_schema: [],
}
