from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

# Based off of https://customer.io/docs/api/track/#operation/entity

template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    type="transformation",
    id="template-downsample",
    name="Downsample",
    description="Downsample events to a percentage of the original",
    icon_url="/static/hedgehog/builder-hog-01.png",
    category=["Custom"],
    hog="""
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
    print('geoip disabled or no ip', event.properties, event.properties?.$ip)
    return event
}

let ip := event.properties.$ip
if (ip == '127.0.0.1') {
    ip := '13.106.122.3' // Spoofing an Australian IP address for local development
}

let response := geoipLookup(ip)
print(response)
if (not response) {
    return event
}

let location := {}
if (response.city) {
    location['city_name'] := response.city.names?.en
}
print(location)
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

let returnEvent := event

returnEvent.properties := returnEvent.properties ?? {}
returnEvent.properties.$set := returnEvent.properties.$set ?? {}
returnEvent.properties.$set_once := returnEvent.properties.$set_once ?? {}


for (let key, value in geoipProperties) {
    // TODO: Modify to only set if the value is not null
    returnEvent.properties.$set[f'$geoip_{key}'] := value
    returnEvent.properties.$set_once[f'$initial_geoip_{key}'] := value
}

for (let key, value in location) {
    returnEvent.properties[f'$geoip_{key}'] := value
    returnEvent.properties.$set[f'$geoip_{key}'] := value
    returnEvent.properties.$set_once[f'$initial_geoip_{key}'] := value
}

return returnEvent
    """.strip(),
    inputs_schema=[],
)
