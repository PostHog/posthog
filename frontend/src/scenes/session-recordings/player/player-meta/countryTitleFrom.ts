import { COUNTRY_CODE_TO_LONG_NAME } from 'lib/utils/country'

export function countryTitleFrom(
    recordingProperties: Record<string, any> | undefined,
    personProperties?: Record<string, any> | undefined
): string {
    // an empty recording bag means the session's properties haven't loaded, so fall back like the list icons do
    const props =
        recordingProperties && Object.keys(recordingProperties).length > 0 ? recordingProperties : personProperties
    if (!props) {
        return ''
    }

    // these prop names are safe between recording and person properties
    // the "initial" person properties share the same name as the event properties
    const country = COUNTRY_CODE_TO_LONG_NAME[props['$geoip_country_code'] as keyof typeof COUNTRY_CODE_TO_LONG_NAME]
    const subdivision = props['$geoip_subdivision_1_name']
    const city = props['$geoip_city_name']

    return [city, subdivision, country].filter(Boolean).join(', ')
}
