import { DateTime, Settings } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './linkedin.template'

jest.setTimeout(60 * 1000)

const buildInputs = (inputs: Record<string, any> = {}): Record<string, any> => {
    return {
        oauth: { access_token: 'oauth-1234' },
        accountId: 'account-12345',
        conversionRuleId: 'conversion-rule-12345',
        conversionDateTime: 1737464596570,
        conversionValue: '100',
        currencyCode: 'USD',
        eventId: 'event-12345',
        userIds: {
            SHA256_EMAIL: '3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98',
            LINKEDIN_FIRST_PARTY_ADS_TRACKING_UUID: 'abc',
        },
        userInfo: { lastName: 'AI', firstName: 'Max', companyName: 'PostHog', countryCode: 'US' },
        ...inputs,
    }
}

describe('linkedin template', () => {
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

    it('works with all properties', async () => {
        const response = await tester.invoke(buildInputs())

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"conversion":"urn:lla:llaPartnerConversion:conversion-rule-12345","conversionHappenedAt":1737464596570,"user":{"userIds":[{"idType":"SHA256_EMAIL","idValue":"3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98"},{"idType":"LINKEDIN_FIRST_PARTY_ADS_TRACKING_UUID","idValue":"abc"}],"userInfo":{"lastName":"AI","firstName":"Max","companyName":"PostHog","countryCode":"US"}},"eventId":"event-12345","conversionValue":{"currencyCode":"USD","amount":"100"}}",
              "headers": {
                "Authorization": "Bearer oauth-1234",
                "Content-Type": "application/json",
                "LinkedIn-Version": "202508",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.linkedin.com/rest/conversionEvents",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('does not contain empty objects', async () => {
        const response = await tester.invoke(
            buildInputs({
                conversionValue: null,
                currencyCode: null,
                userInfo: {},
            })
        )

        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"conversion":"urn:lla:llaPartnerConversion:conversion-rule-12345","conversionHappenedAt":1737464596570,"user":{"userIds":[{"idType":"SHA256_EMAIL","idValue":"3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98"},{"idType":"LINKEDIN_FIRST_PARTY_ADS_TRACKING_UUID","idValue":"abc"}]},"eventId":"event-12345"}",
              "headers": {
                "Authorization": "Bearer oauth-1234",
                "Content-Type": "application/json",
                "LinkedIn-Version": "202508",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.linkedin.com/rest/conversionEvents",
            }
        `)
    })
})
