import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'transformation',
    id: 'template-timestamp-parser',
    name: 'Timestamp Parser',
    description:
        'Parses the event timestamp into separate day of the week, day, month, year, hour and minute properties.',
    icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(event.timestamp)) {
    return event
}

let returnEvent := event
let ts := event.timestamp
let dt := null

if (typeof(ts) == 'string') {
    dt := toDateTime(ts)
} else if (typeof(ts) == 'integer' or typeof(ts) == 'float') {
    // Values large enough to be milliseconds since the epoch are read as milliseconds.
    dt := ts > 999999999999 ? fromUnixTimestampMilli(ts) : fromUnixTimestamp(ts)
}

if (dt != null) {
    returnEvent.properties['day_of_the_week'] := formatDateTime(dt, '%W')
    returnEvent.properties['day'] := extract('day', dt)
    returnEvent.properties['month'] := extract('month', dt)
    returnEvent.properties['year'] := extract('year', dt)
    returnEvent.properties['hour'] := extract('hour', dt)
    returnEvent.properties['minute'] := extract('minute', dt)
}

return returnEvent
    `,
    inputs_schema: [],
}
