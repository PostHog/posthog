import { SessionRecordingType } from '~/types'

import { gatherIconProperties } from './gatherIconProperties'

const recording = {
    person: {
        properties: {
            $geoip_country_code: 'US',
            $browser: 'Chrome',
            $device_type: 'Desktop',
            $os: 'Windows',
        },
    },
} as SessionRecordingType

describe('gatherIconProperties', () => {
    it.each([undefined, {}])('does not use the person country when session properties are %p', (properties) => {
        expect(gatherIconProperties(properties, recording)).toEqual([
            { property: '$browser', value: 'Chrome', label: 'Chrome' },
            { property: '$device_type', value: 'Desktop', label: 'Desktop' },
            { property: '$os', value: 'Windows', label: 'Windows' },
        ])
    })

    it('does not fall back to person country when the loaded session country is null', () => {
        expect(gatherIconProperties({ $geoip_country_code: null }, recording)).toEqual([])
    })

    it('uses each session country instead of the same person country', () => {
        expect(
            ['AR', 'DE'].map(($geoip_country_code) =>
                gatherIconProperties({ $geoip_country_code }, recording).find(
                    ({ property }) => property === '$geoip_country_code'
                )
            )
        ).toEqual([
            { property: '$geoip_country_code', value: 'AR', label: 'Argentina' },
            { property: '$geoip_country_code', value: 'DE', label: 'Germany' },
        ])
    })
})
