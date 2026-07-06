import { DateTime, Settings } from 'luxon'

import { TemplateTester, createAdDestinationPayload } from '../../test/test-helpers'
import { template } from './microsoft.template'

jest.setTimeout(60 * 1000)
describe('microsoft template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        Settings.defaultZone = 'UTC'
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })
    afterEach(() => {
        Settings.defaultZone = 'system'
        jest.useRealTimers()
    })
    it('works with conversion value and currency', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            { tagId: '12345678', apiToken: 'api-token', eventName: 'purchase' },
            createAdDestinationPayload({ event: { properties: { currency: 'USD', value: '100' } } }),
            { currency: '{event.properties.currency}', conversionValue: '{event.properties.value}' }
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":[{"eventType":"custom","eventName":"purchase","eventTime":1735689600,"userData":{"msclkid":"microsoft-id","em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3"},"eventId":"event-id","customData":{"value":100,"currency":"USD"}}]}",
              "headers": {
                "Authorization": "Bearer api-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://capi.uet.microsoft.com/v1/12345678/events",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: {} })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })
    it('works with minimal inputs and hashes the email', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            { tagId: '12345678', apiToken: 'api-token', eventName: 'purchase' },
            createAdDestinationPayload()
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":[{"eventType":"custom","eventName":"purchase","eventTime":1735689600,"userData":{"msclkid":"microsoft-id","em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3"},"eventId":"event-id"}]}",
              "headers": {
                "Authorization": "Bearer api-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://capi.uet.microsoft.com/v1/12345678/events",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: {} })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })
    it('handles error responses', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            { tagId: '12345678', apiToken: 'api-token', eventName: 'purchase' },
            createAdDestinationPayload()
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 401,
            body: { error: { code: 'Unauthorized', message: 'You are not authorized to access this resource.' } },
        })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from capi.uet.microsoft.com (status 401): {'error': {'code': 'Unauthorized', 'message': 'You are not authorized to access this resource.'}}"`
        )
    })
    it('skips when microsoftClickId is missing', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            { tagId: '12345678', apiToken: 'api-token', eventName: 'purchase' },
            createAdDestinationPayload({ person: { properties: { msclkid: null } } })
        )
        expect(response.logs.filter((log) => log.level === 'info').map((log) => log.message)).toMatchInlineSnapshot(
            `
            [
              "Empty \`microsoftClickId\`. Skipping...",
            ]
        `
        )
        expect(response.finished).toEqual(true)
    })
})
