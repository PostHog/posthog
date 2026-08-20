import { TemplateTester, createAdDestinationPayload } from '../../test/test-helpers'
import { template } from './google-data-manager.template'

describe('Google Data Manager template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('sends a Google Ads conversion event', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            {
                oauth: { access_token: 'access-token' },
                customerId: '1231231234/5675675678',
                conversionActionId: '123456789',
            },
            createAdDestinationPayload(),
            {
                gbraid: 'gbraid-id',
                conversionValue: '100',
                currency: 'USD',
                transactionId: 'order-123',
                adUserDataConsent: 'CONSENT_GRANTED',
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{\"destinations\":[{\"operatingAccount\":{\"accountType\":\"GOOGLE_ADS\",\"accountId\":\"1231231234\"},\"productDestinationId\":\"123456789\",\"loginAccount\":{\"accountType\":\"GOOGLE_ADS\",\"accountId\":\"5675675678\"}}],\"events\":[{\"eventTimestamp\":\"2025-01-01T00:00:00Z\",\"eventSource\":\"WEB\",\"adIdentifiers\":{\"gclid\":\"google-id\",\"gbraid\":\"gbraid-id\"},\"userData\":{\"userIdentifiers\":[{\"emailAddress\":\"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3\"}]},\"conversionValue\":100,\"currency\":\"USD\",\"transactionId\":\"order-123\",\"consent\":{\"adUserData\":\"CONSENT_GRANTED\"}}],\"encoding\":\"HEX\"}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://datamanager.googleapis.com/v1/events:ingest",
            }
        `)
    })

    it('skips events without a click ID or user identifier', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            {
                oauth: { access_token: 'access-token' },
                customerId: '1231231234/5675675678',
                conversionActionId: '123456789',
            },
            createAdDestinationPayload({ person: { properties: { email: null, gclid: null } } })
        )

        expect(response.finished).toEqual(true)
        expect(response.logs.filter((log) => log.level === 'info').map((log) => log.message)).toEqual([
            'No click ID or user identifiers. Skipping...',
        ])
    })
})
