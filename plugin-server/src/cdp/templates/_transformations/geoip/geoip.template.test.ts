import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './geoip.template'

describe('geoip.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(new Date('2025-01-01'))
    })

    it('should enrich event with IP location', async () => {
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

    it('should enrich person with IP location', async () => {
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
        // Check $set properties
        expect((response.execResult as any).properties.$set).toEqual(
            expect.objectContaining({
                $geoip_city_name: 'Linköping',
                $geoip_country_name: 'Sweden',
                $geoip_country_code: 'SE',
                $geoip_continent_name: 'Europe',
                $geoip_continent_code: 'EU',
                $geoip_latitude: 58.4167,
                $geoip_longitude: 15.6167,
                $geoip_time_zone: 'Europe/Stockholm',
                $geoip_subdivision_1_code: 'E',
                $geoip_subdivision_1_name: 'Östergötland County',
            })
        )

        // Check $set_once properties
        expect((response.execResult as any).properties.$set_once).toEqual(
            expect.objectContaining({
                $initial_geoip_city_name: 'Linköping',
                $initial_geoip_country_name: 'Sweden',
                $initial_geoip_country_code: 'SE',
                $initial_geoip_continent_name: 'Europe',
                $initial_geoip_continent_code: 'EU',
                $initial_geoip_latitude: 58.4167,
                $initial_geoip_longitude: 15.6167,
                $initial_geoip_time_zone: 'Europe/Stockholm',
                $initial_geoip_subdivision_1_code: 'E',
                $initial_geoip_subdivision_1_name: 'Östergötland County',
            })
        )
    })

    it('should set properties to null if no values present', async () => {
        // First call beforeEach with a transform function to remove city data
        await tester.beforeEach((res) => {
            const { city, ...remainingResult } = res
            return remainingResult
        })

        // Then create the mock globals and run the test
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

        expect((response.execResult as any).properties.$set).toMatchInlineSnapshot(`
          {
            "$geoip_accuracy_radius": 76,
            "$geoip_city_confidence": null,
            "$geoip_city_name": null,
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
          }
        `)

        expect((response.execResult as any).properties.$set_once).toMatchInlineSnapshot(`
          {
            "$initial_geoip_accuracy_radius": 76,
            "$initial_geoip_city_confidence": null,
            "$initial_geoip_city_name": null,
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
          }
        `)
    })

    it('should skip processing when $geoip_disable is true', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $ip: '89.160.20.129',
                    $geoip_disable: true,
                },
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        // Verify the event was not modified
        expect((response.execResult as any).properties).toEqual({
            $ip: '89.160.20.129',
            $geoip_disable: true,
        })
    })
})
