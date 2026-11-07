import { COUNTRY_CODE_TO_LONG_NAME } from 'lib/utils/country'

export function countryTitleFrom(recordingProperties: Record<string, any> | undefined): string {
    // Person location can belong to a different session.
    const props = recordingProperties
    if (!props) {
        return ''
    }

    const country = COUNTRY_CODE_TO_LONG_NAME[props['$geoip_country_code'] as keyof typeof COUNTRY_CODE_TO_LONG_NAME]
    const subdivision = props['$geoip_subdivision_1_name']
    const city = props['$geoip_city_name']

    return [city, subdivision, country].filter(Boolean).join(', ')
}
