import { DateTime } from 'luxon'

import { TemplateTester, createAdDestinationPayload } from '../../test/test-helpers'
import { template } from './adjust.template'

jest.setTimeout(2 * 60 * 1000)

describe('adjust template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('sends a basic event with device identifiers', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                appToken: 'test-app-token',
                environment: 'production',
                deviceIdentifiers: {
                    idfa: 'D2CADB5F-410F-4963-AC0C-2A78534BDF1E',
                },
            },
            createAdDestinationPayload(),
            {
                eventToken: 'abc123',
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "s2s=1&app_token=test-app-token&event_token=abc123&environment=production&idfa=D2CADB5F-410F-4963-AC0C-2A78534BDF1E&created_at_unix=1735689600",
              "headers": {
                "Content-Type": "application/x-www-form-urlencoded",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://s2s.adjust.com/event",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('includes revenue and currency', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                appToken: 'test-app-token',
                environment: 'production',
                deviceIdentifiers: {
                    gps_adid: '38400000-8cf0-11bd-b23e-10b96e40000d',
                },
            },
            createAdDestinationPayload({
                event: {
                    properties: {
                        revenue: 29.99,
                        currency: 'USD',
                    },
                },
            }),
            {
                eventToken: 'rev123',
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "s2s=1&app_token=test-app-token&event_token=rev123&environment=production&gps_adid=38400000-8cf0-11bd-b23e-10b96e40000d&revenue=29.99&currency=USD&created_at_unix=1735689600",
              "headers": {
                "Content-Type": "application/x-www-form-urlencoded",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://s2s.adjust.com/event",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('includes callback and partner params', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                appToken: 'test-app-token',
                environment: 'sandbox',
                deviceIdentifiers: {
                    idfa: 'test-idfa',
                },
            },
            createAdDestinationPayload(),
            {
                eventToken: 'evt456',
                callbackParams: { order_id: '12345', user_type: 'premium' },
                partnerParams: { campaign: 'summer_sale' },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "s2s=1&app_token=test-app-token&event_token=evt456&environment=sandbox&idfa=test-idfa&callback_params=%7B%22order_id%22%3A%2212345%22%2C%22user_type%22%3A%22premium%22%7D&partner_params=%7B%22campaign%22%3A%22summer_sale%22%7D&created_at_unix=1735689600",
              "headers": {
                "Content-Type": "application/x-www-form-urlencoded",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://s2s.adjust.com/event",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('forwards ip address and user agent', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                appToken: 'test-app-token',
                environment: 'production',
                deviceIdentifiers: {
                    idfa: 'test-idfa',
                },
            },
            createAdDestinationPayload({
                event: {
                    properties: {
                        $ip: '123.123.123.123',
                        $raw_user_agent: 'MyApp/1.0 (iPhone; iOS 17.0)',
                    },
                },
            }),
            {
                eventToken: 'evt789',
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "s2s=1&app_token=test-app-token&event_token=evt789&environment=production&idfa=test-idfa&ip_address=123.123.123.123&user_agent=MyApp%2F1.0%20(iPhone%3B%20iOS%2017.0)&created_at_unix=1735689600",
              "headers": {
                "Content-Type": "application/x-www-form-urlencoded",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://s2s.adjust.com/event",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('handles error responses', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                appToken: 'test-app-token',
                environment: 'production',
                deviceIdentifiers: {
                    idfa: 'test-idfa',
                },
            },
            createAdDestinationPayload(),
            {
                eventToken: 'evt123',
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { error: 'Bad Request: invalid event token' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toContain('Error from s2s.adjust.com (status 400)')
    })

    it.each([['missing app token', { environment: 'production', deviceIdentifiers: { idfa: 'test' } }]])(
        'handles %s',
        async (_, settings) => {
            const response = await tester.invokeMapping('Order Completed', settings, createAdDestinationPayload(), {
                eventToken: 'evt123',
            })

            expect(response.error).toMatchInlineSnapshot(`"Adjust app token is required"`)
            expect(response.finished).toEqual(true)
        }
    )

    it('handles missing event token', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                appToken: 'test-app-token',
                environment: 'production',
                deviceIdentifiers: {
                    idfa: 'test-idfa',
                },
            },
            createAdDestinationPayload(),
            {
                eventToken: '',
            }
        )

        expect(response.error).toMatchInlineSnapshot(`"Adjust event token is required"`)
        expect(response.finished).toEqual(true)
    })

    it('handles missing device identifiers', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                appToken: 'test-app-token',
                environment: 'production',
                deviceIdentifiers: {},
            },
            createAdDestinationPayload(),
            {
                eventToken: 'evt123',
            }
        )

        expect(response.error).toMatchInlineSnapshot(
            `"At least one device identifier is required (idfa, gps_adid, android_id, idfv, or adid)"`
        )
        expect(response.finished).toEqual(true)
    })

    it('sends multiple device identifiers', async () => {
        const response = await tester.invokeMapping(
            'Application Installed',
            {
                appToken: 'test-app-token',
                environment: 'sandbox',
                deviceIdentifiers: {
                    idfa: 'D2CADB5F-410F-4963-AC0C-2A78534BDF1E',
                    idfv: 'A1B2C3D4-E5F6-7890-ABCD-EF1234567890',
                },
            },
            createAdDestinationPayload({
                event: {
                    event: 'Application Installed',
                },
            }),
            {
                eventToken: 'install1',
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "s2s=1&app_token=test-app-token&event_token=install1&environment=sandbox&idfa=D2CADB5F-410F-4963-AC0C-2A78534BDF1E&idfv=A1B2C3D4-E5F6-7890-ABCD-EF1234567890&created_at_unix=1735689600",
              "headers": {
                "Content-Type": "application/x-www-form-urlencoded",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://s2s.adjust.com/event",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })
})
