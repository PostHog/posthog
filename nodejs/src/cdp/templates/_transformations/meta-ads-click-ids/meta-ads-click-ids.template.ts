import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'transformation',
    id: 'template-meta-ads-click-ids',
    name: 'Meta Ads click IDs',
    description:
        "Stores Meta's fbc and fbp identifiers on the person the first time they are seen, so the Meta Ads Conversions destination can send a fixed click time instead of recomputing it on every event.",
    icon_url: '/static/services/meta-ads.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// fbc and fbp both embed the moment the click or the browser was first seen. Deriving them per event
// would keep pushing that moment forward, so mint them once here and pin them to the person.
let returnEvent := event
returnEvent.properties := returnEvent.properties ?? {}
returnEvent.properties.$set_once := returnEvent.properties.$set_once ?? {}

// toUnixTimestampMilli returns seconds * 1000 as a float, so toInt keeps it out of decimal form
let observedAtMs := 0
if (not empty(event.timestamp)) {
    observedAtMs := toInt(toUnixTimestampMilli(event.timestamp)) ?? 0
}
if (observedAtMs <= 0) {
    observedAtMs := toInt(toUnixTimestampMilli(now()))
}

// fbp is Meta's first-party browser identifier: fb.<subdomainIndex>.<creationTimeMs>.<random>
let fbpRandom := 1000000000 + toInt(floor(randomFloat() * 9000000000))
returnEvent.properties.$set_once['$meta_fbp'] := f'fb.1.{observedAtMs}.{fbpRandom}'

if (not empty(event.properties.fbclid)) {
    let clickId := toString(event.properties.fbclid)
    if (match(clickId, '^fb[.][0-9]+[.][0-9]+[.][A-Za-z0-9_-]+$')) {
        // Already a full fbc value, so keep the click time it carries
        returnEvent.properties.$set_once['$meta_fbc'] := clickId
    } else if (match(clickId, '^[A-Za-z0-9_-]+$')) {
        returnEvent.properties.$set_once['$meta_fbc'] := f'fb.1.{observedAtMs}.{clickId}'
    }
}

return returnEvent
    `,
    inputs_schema: [],
}
