import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation',
    id: 'template-user-agent',
    name: 'User Agent Populator',
    description:
        'Reads the user agent from the event and sets $browser, $browser_version, $os, $device and $device_type from it.',
    icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(event.properties)) {
    return event
}

let ua := event.properties.$useragent ?? event.properties['$user-agent'] ?? event.properties.$user_agent
if (empty(ua) or typeof(ua) != 'string') {
    return event
}

// Do not overwrite browser or device properties the SDK already set, unless asked to.
let hasExisting := not empty(event.properties.$browser)
    or not empty(event.properties.$browser_version)
    or not empty(event.properties.$os)
    or not empty(event.properties.$device)
    or not empty(event.properties.$device_type)
if (hasExisting and not inputs.overrideExisting) {
    return event
}

let parsed := parseUserAgent(ua)
if (empty(parsed)) {
    return event
}

let returnEvent := event
returnEvent.properties.$device := parsed.device
returnEvent.properties.$device_type := parsed.deviceType
if (not empty(parsed.browser)) {
    returnEvent.properties.$browser := parsed.browser
    returnEvent.properties.$browser_version := parsed.browserVersion
    returnEvent.properties.$os := parsed.os
    returnEvent.properties.$browser_type := parsed.browserType
}

// Strip the raw user agent values now that they are parsed.
if (not empty(event.properties.$useragent)) {
    returnEvent.properties.$useragent := null
}
if (not empty(event.properties['$user-agent'])) {
    returnEvent.properties['$user-agent'] := null
}
if (not empty(event.properties.$user_agent)) {
    returnEvent.properties.$user_agent := null
}

return returnEvent
    `,
    inputs_schema: [
        {
            key: 'overrideExisting',
            type: 'boolean',
            label: 'Override existing properties',
            description: 'Replace $browser, $os and device properties even when the event already has them.',
            default: false,
            required: false,
        },
    ],
}
