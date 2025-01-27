import { Reader } from '@maxmind/geoip2-node'
import { PluginEvent } from '@posthog/plugin-scaffold'
import { readFileSync } from 'fs'
import { join } from 'path'
import { brotliDecompressSync } from 'zlib'

import { template as geoipTemplate } from '~/src/cdp/templates/_transformations/geoip/geoip.template'
import { compileHog } from '~/src/cdp/templates/compiler'
import { createHogFunction } from '~/tests/cdp/fixtures'

import { Hub } from '../../types'
import { createHub } from '../../utils/db/hub'
import { HogTransformerService } from './hog-transformer.service'

let mockGetTeamHogFunctions: jest.Mock

jest.mock('../../utils/status', () => ({
    status: {
        warn: jest.fn(),
        info: jest.fn(),
        debug: jest.fn(),
        updatePrompt: jest.fn(),
    },
}))

jest.mock('../../cdp/services/hog-function-manager.service', () => ({
    HogFunctionManagerService: jest.fn().mockImplementation(() => ({
        getTeamHogFunctions: (mockGetTeamHogFunctions = jest.fn().mockReturnValue([])),
    })),
}))

describe('HogTransformer', () => {
    let hub: Hub
    let hogTransformer: HogTransformerService

    const mmdbBrotliContents = readFileSync(join(__dirname, '../../../tests/assets/GeoLite2-City-Test.mmdb.br'))

    beforeEach(async () => {
        hub = await createHub()
        hub.mmdb = Reader.openBuffer(brotliDecompressSync(mmdbBrotliContents))
        hogTransformer = new HogTransformerService(hub)
    })

    describe('transformEvent', () => {
        it('handles geoip lookup transformation', async () => {
            jest.useFakeTimers()
            jest.setSystemTime(new Date('2024-06-07T12:00:00.000Z'))

            const hogByteCode = await compileHog(geoipTemplate.hog)
            const geoIpFunction = createHogFunction({
                ...geoipTemplate,
                bytecode: hogByteCode,
            })

            mockGetTeamHogFunctions.mockReturnValue([geoIpFunction])

            const event: PluginEvent = {
                ip: '89.160.20.129',
                site_url: 'http://localhost',
                team_id: 1,
                now: '2024-06-07T12:00:00.000Z',
                uuid: 'event-id',
                event: 'event-name',
                distinct_id: 'distinct-id',
                properties: { $current_url: 'https://example.com', $ip: '89.160.20.129' },
                timestamp: '2024-01-01T00:00:00Z',
            }

            const result = await hogTransformer.transformEvent(event)

            expect(result.properties).toEqual({
                $current_url: 'https://example.com',
                $ip: '89.160.20.129',
                $set: {
                    $geoip_city_name: 'Linköping',
                    $geoip_city_confidence: null,
                    $geoip_subdivision_2_name: null,
                    $geoip_subdivision_2_code: null,
                    $geoip_subdivision_1_name: 'Östergötland County',
                    $geoip_subdivision_1_code: 'E',
                    $geoip_country_name: 'Sweden',
                    $geoip_country_code: 'SE',
                    $geoip_continent_name: 'Europe',
                    $geoip_continent_code: 'EU',
                    $geoip_postal_code: null,
                    $geoip_latitude: 58.4167,
                    $geoip_longitude: 15.6167,
                    $geoip_accuracy_radius: 76,
                    $geoip_time_zone: 'Europe/Stockholm',
                },
                $set_once: {
                    $initial_geoip_city_name: 'Linköping',
                    $initial_geoip_city_confidence: null,
                    $initial_geoip_subdivision_2_name: null,
                    $initial_geoip_subdivision_2_code: null,
                    $initial_geoip_subdivision_1_name: 'Östergötland County',
                    $initial_geoip_subdivision_1_code: 'E',
                    $initial_geoip_country_name: 'Sweden',
                    $initial_geoip_country_code: 'SE',
                    $initial_geoip_continent_name: 'Europe',
                    $initial_geoip_continent_code: 'EU',
                    $initial_geoip_postal_code: null,
                    $initial_geoip_latitude: 58.4167,
                    $initial_geoip_longitude: 15.6167,
                    $initial_geoip_accuracy_radius: 76,
                    $initial_geoip_time_zone: 'Europe/Stockholm',
                },
                $geoip_city_name: 'Linköping',
                $geoip_country_name: 'Sweden',
                $geoip_country_code: 'SE',
                $geoip_continent_name: 'Europe',
                $geoip_continent_code: 'EU',
                $geoip_latitude: 58.4167,
                $geoip_longitude: 15.6167,
                $geoip_accuracy_radius: 76,
                $geoip_time_zone: 'Europe/Stockholm',
                $geoip_subdivision_1_code: 'E',
                $geoip_subdivision_1_name: 'Östergötland County',
            })
        })
    })
})
