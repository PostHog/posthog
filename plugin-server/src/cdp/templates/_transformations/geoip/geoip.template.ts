import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha', // TODO: change to beta once we want to enable it by default for every project.
    type: 'transformation',
    id: 'template-geoip',
    name: 'GeoIP',
    description: 'Adds geoip data to the event',
    icon_url: '/static/transformations/geoip.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// Define the properties to be added to the event
let geoipProperties := {
    'city_name': null,
    'city_confidence': null,
    'subdivision_2_name': null,
    'subdivision_2_code': null,
    'subdivision_1_name': null,
    'subdivision_1_code': null,
    'country_name': null,
    'country_code': null,
    'continent_name': null,
    'continent_code': null,
    'postal_code': null,
    'latitude': null,
    'longitude': null,
    'accuracy_radius': null,
    'time_zone': null
}
// Check if the event has an IP address
if (event.properties?.$geoip_disable or empty(event.properties?.$ip)) {
    print('geoip disabled or no ip.')
    return event
}
let ip := event.properties.$ip
if (ip == '127.0.0.1') {
    print('spoofing ip for local development', ip)
    ip := '89.160.20.129'
}
let response := geoipLookup(ip)
if (not response) {
    print('geoip lookup failed for ip', ip)
    return event
}
let location := {}
if (response.city) {
    location['city_name'] := response.city.names?.en
}
if (response.country) {
    location['country_name'] := response.country.names?.en
    location['country_code'] := response.country.isoCode
}
if (response.continent) {
    location['continent_name'] := response.continent.names?.en
    location['continent_code'] := response.continent.code
}
if (response.postal) {
    location['postal_code'] := response.postal.code
}
if (response.location) {
    location['latitude'] := response.location?.latitude
    location['longitude'] := response.location?.longitude
    location['accuracy_radius'] := response.location?.accuracyRadius
    location['time_zone'] := response.location?.timeZone
}
if (response.subdivisions) {
    for (let index, subdivision in response.subdivisions) {
        location[f'subdivision_{index + 1}_code'] := subdivision.isoCode
        location[f'subdivision_{index + 1}_name'] := subdivision.names?.en
    }
}
print('geoip location data for ip:', location) 
let returnEvent := event
returnEvent.properties := returnEvent.properties ?? {}
returnEvent.properties.$set := returnEvent.properties.$set ?? {}
returnEvent.properties.$set_once := returnEvent.properties.$set_once ?? {}
for (let key, value in geoipProperties) {
    if (value != null) {
        returnEvent.properties.$set[f'$geoip_{key}'] := value
        returnEvent.properties.$set_once[f'$initial_geoip_{key}'] := value
    }
    returnEvent.properties.$set[f'$geoip_{key}'] := value
    returnEvent.properties.$set_once[f'$initial_geoip_{key}'] := value
}
for (let key, value in location) {
    returnEvent.properties[f'$geoip_{key}'] := value
    returnEvent.properties.$set[f'$geoip_{key}'] := value
    returnEvent.properties.$set_once[f'$initial_geoip_{key}'] := value
}
return returnEvent
    `,
    inputs_schema: [],
}
