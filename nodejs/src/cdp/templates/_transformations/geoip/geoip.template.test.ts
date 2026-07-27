import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './geoip.template'

describe('geoip.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = new Date('2025-01-01')
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('should enrich event with IP location', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $ip: '216.160.83.56',
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
                "$geoip_accuracy_radius": 22,
                "$geoip_city_name": "Milton",
                "$geoip_continent_code": "NA",
                "$geoip_continent_name": "North America",
                "$geoip_country_code": "US",
                "$geoip_country_name": "United States",
                "$geoip_latitude": 47.2513,
                "$geoip_longitude": -122.3149,
                "$geoip_postal_code": "98354",
                "$geoip_subdivision_1_code": "WA",
                "$geoip_subdivision_1_name": "Washington",
                "$geoip_time_zone": "America/Los_Angeles",
                "$ip": "216.160.83.56",
                "$set": {
                  "$geoip_accuracy_radius": 22,
                  "$geoip_city_confidence": null,
                  "$geoip_city_name": "Milton",
                  "$geoip_continent_code": "NA",
                  "$geoip_continent_name": "North America",
                  "$geoip_country_code": "US",
                  "$geoip_country_name": "United States",
                  "$geoip_latitude": 47.2513,
                  "$geoip_longitude": -122.3149,
                  "$geoip_postal_code": "98354",
                  "$geoip_subdivision_1_code": "WA",
                  "$geoip_subdivision_1_name": "Washington",
                  "$geoip_subdivision_2_code": null,
                  "$geoip_subdivision_2_name": null,
                  "$geoip_time_zone": "America/Los_Angeles",
                },
                "$set_once": {
                  "$initial_geoip_accuracy_radius": 22,
                  "$initial_geoip_city_confidence": null,
                  "$initial_geoip_city_name": "Milton",
                  "$initial_geoip_continent_code": "NA",
                  "$initial_geoip_continent_name": "North America",
                  "$initial_geoip_country_code": "US",
                  "$initial_geoip_country_name": "United States",
                  "$initial_geoip_latitude": 47.2513,
                  "$initial_geoip_longitude": -122.3149,
                  "$initial_geoip_postal_code": "98354",
                  "$initial_geoip_subdivision_1_code": "WA",
                  "$initial_geoip_subdivision_1_name": "Washington",
                  "$initial_geoip_subdivision_2_code": null,
                  "$initial_geoip_subdivision_2_name": null,
                  "$initial_geoip_time_zone": "America/Los_Angeles",
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
                    $ip: '216.160.83.56',
                },
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        // Check $set properties
        expect((response.execResult as any).properties.$set).toMatchInlineSnapshot(`
            {
              "$geoip_accuracy_radius": 22,
              "$geoip_city_confidence": null,
              "$geoip_city_name": "Milton",
              "$geoip_continent_code": "NA",
              "$geoip_continent_name": "North America",
              "$geoip_country_code": "US",
              "$geoip_country_name": "United States",
              "$geoip_latitude": 47.2513,
              "$geoip_longitude": -122.3149,
              "$geoip_postal_code": "98354",
              "$geoip_subdivision_1_code": "WA",
              "$geoip_subdivision_1_name": "Washington",
              "$geoip_subdivision_2_code": null,
              "$geoip_subdivision_2_name": null,
              "$geoip_time_zone": "America/Los_Angeles",
            }
        `)

        // Check $set_once properties
        expect((response.execResult as any).properties.$set_once).toMatchInlineSnapshot(`
            {
              "$initial_geoip_accuracy_radius": 22,
              "$initial_geoip_city_confidence": null,
              "$initial_geoip_city_name": "Milton",
              "$initial_geoip_continent_code": "NA",
              "$initial_geoip_continent_name": "North America",
              "$initial_geoip_country_code": "US",
              "$initial_geoip_country_name": "United States",
              "$initial_geoip_latitude": 47.2513,
              "$initial_geoip_longitude": -122.3149,
              "$initial_geoip_postal_code": "98354",
              "$initial_geoip_subdivision_1_code": "WA",
              "$initial_geoip_subdivision_1_name": "Washington",
              "$initial_geoip_subdivision_2_code": null,
              "$initial_geoip_subdivision_2_name": null,
              "$initial_geoip_time_zone": "America/Los_Angeles",
            }
        `)
    })

    it('should set properties to null if no values present', async () => {
        // First call beforeEach with a transform function to remove city data
        await tester.beforeEach()

        const actualResult = tester.geoIp?.city('216.160.83.56')

        jest.spyOn(tester.geoIp!, 'city').mockReturnValue({
            ...actualResult,
            city: undefined,
        } as any)

        // Then create the mock globals and run the test
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $ip: '216.160.83.56',
                },
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        expect((response.execResult as any).properties.$set).toMatchInlineSnapshot(`
            {
              "$geoip_accuracy_radius": 22,
              "$geoip_city_confidence": null,
              "$geoip_city_name": null,
              "$geoip_continent_code": "NA",
              "$geoip_continent_name": "North America",
              "$geoip_country_code": "US",
              "$geoip_country_name": "United States",
              "$geoip_latitude": 47.2513,
              "$geoip_longitude": -122.3149,
              "$geoip_postal_code": "98354",
              "$geoip_subdivision_1_code": "WA",
              "$geoip_subdivision_1_name": "Washington",
              "$geoip_subdivision_2_code": null,
              "$geoip_subdivision_2_name": null,
              "$geoip_time_zone": "America/Los_Angeles",
            }
        `)

        expect((response.execResult as any).properties.$set_once).toMatchInlineSnapshot(`
            {
              "$initial_geoip_accuracy_radius": 22,
              "$initial_geoip_city_confidence": null,
              "$initial_geoip_city_name": null,
              "$initial_geoip_continent_code": "NA",
              "$initial_geoip_continent_name": "North America",
              "$initial_geoip_country_code": "US",
              "$initial_geoip_country_name": "United States",
              "$initial_geoip_latitude": 47.2513,
              "$initial_geoip_longitude": -122.3149,
              "$initial_geoip_postal_code": "98354",
              "$initial_geoip_subdivision_1_code": "WA",
              "$initial_geoip_subdivision_1_name": "Washington",
              "$initial_geoip_subdivision_2_code": null,
              "$initial_geoip_subdivision_2_name": null,
              "$initial_geoip_time_zone": "America/Los_Angeles",
            }
        `)
    })

    it('should skip processing when $geoip_disable is true', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $ip: '216.160.83.56',
                    $geoip_disable: true,
                },
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        // Verify the event was not modified
        expect((response.execResult as any).properties).toEqual({
            $ip: '216.160.83.56',
            $geoip_disable: true,
        })
    })
})
