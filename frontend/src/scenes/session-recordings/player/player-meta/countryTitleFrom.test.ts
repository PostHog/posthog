import { countryTitleFrom } from './countryTitleFrom'

describe('countryTitleFrom', () => {
    it.each([undefined, {}, { $geoip_country_code: null }])(
        'has no location without session data: %p',
        (properties) => {
            expect(countryTitleFrom(properties)).toBe('')
        }
    )

    it('uses the session location', () => {
        expect(
            countryTitleFrom({
                $geoip_country_code: 'DE',
                $geoip_subdivision_1_name: 'Berlin',
                $geoip_city_name: 'Berlin',
            })
        ).toBe('Berlin, Berlin, Germany')
    })
})
