import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './geoip.template'

describe('geoip template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(new Date('2025-01-01'))
    })

    it('enrich event with IP location', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $ip: '89.160.20.129',
                },
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchInlineSnapshot(`
            {
              "distinct_id": "distinct-id",
              "elements_chain": "",
              "event": "event-name",
              "properties": {
                "$geoip_accuracy_radius": 76,
                "$geoip_city_name": "Linköping",
                "$geoip_continent_code": "EU",
                "$geoip_continent_name": "Europe",
                "$geoip_country_code": "SE",
                "$geoip_country_name": "Sweden",
                "$geoip_latitude": 58.4167,
                "$geoip_longitude": 15.6167,
                "$geoip_subdivision_1_code": "E",
                "$geoip_subdivision_1_name": "Östergötland County",
                "$geoip_time_zone": "Europe/Stockholm",
                "$ip": "89.160.20.129",
                "$set": {
                  "$geoip_accuracy_radius": 76,
                  "$geoip_city_confidence": null,
                  "$geoip_city_name": "Linköping",
                  "$geoip_continent_code": "EU",
                  "$geoip_continent_name": "Europe",
                  "$geoip_country_code": "SE",
                  "$geoip_country_name": "Sweden",
                  "$geoip_latitude": 58.4167,
                  "$geoip_longitude": 15.6167,
                  "$geoip_postal_code": null,
                  "$geoip_subdivision_1_code": "E",
                  "$geoip_subdivision_1_name": "Östergötland County",
                  "$geoip_subdivision_2_code": null,
                  "$geoip_subdivision_2_name": null,
                  "$geoip_time_zone": "Europe/Stockholm",
                },
                "$set_once": {
                  "$initial_geoip_accuracy_radius": 76,
                  "$initial_geoip_city_confidence": null,
                  "$initial_geoip_city_name": "Linköping",
                  "$initial_geoip_continent_code": "EU",
                  "$initial_geoip_continent_name": "Europe",
                  "$initial_geoip_country_code": "SE",
                  "$initial_geoip_country_name": "Sweden",
                  "$initial_geoip_latitude": 58.4167,
                  "$initial_geoip_longitude": 15.6167,
                  "$initial_geoip_postal_code": null,
                  "$initial_geoip_subdivision_1_code": "E",
                  "$initial_geoip_subdivision_1_name": "Östergötland County",
                  "$initial_geoip_subdivision_2_code": null,
                  "$initial_geoip_subdivision_2_name": null,
                  "$initial_geoip_time_zone": "Europe/Stockholm",
                },
              },
              "timestamp": "2024-01-01T00:00:00Z",
              "url": "https://us.posthog.com/projects/1/events/1234",
              "uuid": "event-id",
            }
        `)
    })
})
