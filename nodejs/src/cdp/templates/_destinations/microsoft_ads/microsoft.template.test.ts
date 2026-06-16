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
            {
                oauth: { access_token: 'access-token' },
                customerId: '1231231234',
                customerAccountId: '5675675678',
                conversionName: 'Purchase',
            },
            createAdDestinationPayload({
                event: { properties: { currency: 'USD', value: '100' } },
            }),
            { conversionCurrencyCode: '{event.properties.currency}', conversionValue: '{event.properties.value}' }
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"OfflineConversions":[{"MicrosoftClickId":"microsoft-id","ConversionName":"Purchase","ConversionTime":"2025-01-01T00:00:00Z","ConversionValue":100,"ConversionCurrencyCode":"USD"}]}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "CustomerAccountId": "5675675678",
                "CustomerId": "1231231234",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://campaign.api.bingads.microsoft.com/CampaignManagement/v13/OfflineConversions/Apply",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: {} })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })
    it('works with empty optional properties', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            {
                oauth: { access_token: 'access-token' },
                customerId: '1231231234',
                customerAccountId: '5675675678',
                conversionName: 'Purchase',
            },
            createAdDestinationPayload()
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"OfflineConversions":[{"MicrosoftClickId":"microsoft-id","ConversionName":"Purchase","ConversionTime":"2025-01-01T00:00:00Z"}]}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "CustomerAccountId": "5675675678",
                "CustomerId": "1231231234",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://campaign.api.bingads.microsoft.com/CampaignManagement/v13/OfflineConversions/Apply",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: {} })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })
    it('handles error responses', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            {
                oauth: { access_token: 'access-token' },
                customerId: '1231231234',
                customerAccountId: '5675675678',
                conversionName: 'Purchase',
            },
            createAdDestinationPayload()
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { Message: 'Invalid conversion' },
        })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from campaign.api.bingads.microsoft.com (status 400): {'Message': 'Invalid conversion'}"`
        )
    })
    it('handles partial errors', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            {
                oauth: { access_token: 'access-token' },
                customerId: '1231231234',
                customerAccountId: '5675675678',
                conversionName: 'Purchase',
            },
            createAdDestinationPayload()
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { PartialErrors: [{ Code: 1, Message: 'ClickId not found' }] },
        })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from campaign.api.bingads.microsoft.com (status 200): [{'Code': 1, 'Message': 'ClickId not found'}]"`
        )
    })
    it('skips when microsoftClickId is missing', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            {
                oauth: { access_token: 'access-token' },
                customerId: '1231231234',
                customerAccountId: '5675675678',
                conversionName: 'Purchase',
            },
            createAdDestinationPayload({ person: { properties: { msclkid: null } } })
        )
        expect(response.logs.filter((log) => log.level === 'info').map((log) => log.message)).toMatchInlineSnapshot(`
            [
              "Empty \`microsoftClickId\`. Skipping...",
            ]
        `)
        expect(response.finished).toEqual(true)
    })
})
