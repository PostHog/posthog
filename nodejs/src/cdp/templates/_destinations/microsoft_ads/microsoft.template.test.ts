import { DateTime, Settings } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

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
    it('works with conversion value, currency and request context', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            { tagId: '12345678', apiToken: 'api-token', eventName: 'purchase' },
            createAdDestinationPayload({
                event: {
                    properties: {
                        currency: 'USD',
                        value: '100',
                        $ip: '203.0.113.1',
                        $raw_user_agent: 'Mozilla/5.0',
                        $current_url: 'https://example.com/checkout',
                    },
                },
            }),
            { currency: '{event.properties.currency}', conversionValue: '{event.properties.value}' }
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":[{"eventType":"custom","eventName":"purchase","eventTime":1735689600,"userData":{"msclkid":"microsoft-id","em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","ph":"422ce82c6fc1724ac878042f7d055653ab5e983d186e616826a72d4384b68af8","externalId":"c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646","clientIpAddress":"203.0.113.1","clientUserAgent":"Mozilla/5.0"},"eventId":"event-id","eventSourceUrl":"https://example.com/checkout","customData":{"value":100,"currency":"USD"}}],"dataProvider":"posthog"}",
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
              "body": "{"data":[{"eventType":"custom","eventName":"purchase","eventTime":1735689600,"userData":{"msclkid":"microsoft-id","em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","ph":"422ce82c6fc1724ac878042f7d055653ab5e983d186e616826a72d4384b68af8","externalId":"c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646"},"eventId":"event-id"}],"dataProvider":"posthog"}",
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
    it('leaves out a source URL that is not an http(s) URL', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            { tagId: '12345678', apiToken: 'api-token', eventName: 'purchase' },
            createAdDestinationPayload({ event: { properties: { $current_url: 'capacitor://localhost/checkout' } } })
        )
        expect(response.error).toBeUndefined()
        const body = parseJSON((response.invocation.queueParameters as { body: string }).body)
        expect(body.data[0].eventSourceUrl).toBeUndefined()
    })
    // Any one identifier is enough for Microsoft to attribute, so none of them may gate the send
    it.each([
        ['click id', { email: null, phone: null, external_id: null }, { msclkid: 'microsoft-id' }],
        [
            'email',
            { msclkid: null, phone: null, external_id: null },
            { em: '3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3' },
        ],
        [
            'phone',
            { msclkid: null, email: null, external_id: null },
            { ph: '422ce82c6fc1724ac878042f7d055653ab5e983d186e616826a72d4384b68af8' },
        ],
        [
            'external id',
            { msclkid: null, email: null, phone: null },
            { externalId: 'c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646' },
        ],
        // Person properties keep their JSON type, so a numeric ID must hash like its string form
        [
            'numeric external id',
            { msclkid: null, email: null, phone: null, external_id: 1234567890 },
            { externalId: 'c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646' },
        ],
    ])('sends the conversion when only %s is available', async (_, personProperties, expectedUserData) => {
        const response = await tester.invokeMapping(
            'Conversion',
            { tagId: '12345678', apiToken: 'api-token', eventName: 'purchase' },
            createAdDestinationPayload({ person: { properties: personProperties } })
        )
        expect(response.error).toBeUndefined()
        const body = parseJSON((response.invocation.queueParameters as { body: string }).body)
        expect(body.data[0].userData).toEqual(expectedUserData)
    })
    it('skips when no identifier is available', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            { tagId: '12345678', apiToken: 'api-token', eventName: 'purchase' },
            createAdDestinationPayload({
                person: { properties: { msclkid: null, email: null, phone: null, external_id: null } },
                event: { properties: { $ip: '203.0.113.1', $raw_user_agent: 'Mozilla/5.0' } },
            })
        )
        expect(response.logs.filter((log) => log.level === 'info').map((log) => log.message)).toMatchInlineSnapshot(
            `
            [
              "No \`microsoftClickId\`, \`email\`, \`phone\` or \`externalId\` to identify the user with. Skipping...",
            ]
        `
        )
        expect(response.finished).toEqual(true)
    })
    // Expected hashes for john@contoso.com and +14255551234 are the examples in Microsoft's CAPI docs
    it.each([
        [
            'email dots, alias and case',
            { email: '  J.o.h.n+ads@Contoso.com ' },
            { em: 'ec81f3ac7b2b19675bab9d54cf416f9f18cff87c97da5cca82c0f0891bc40602' },
        ],
        [
            'pre-hashed email',
            { email: 'EC81F3AC7B2B19675BAB9D54CF416F9F18CFF87C97DA5CCA82C0F0891BC40602' },
            { em: 'ec81f3ac7b2b19675bab9d54cf416f9f18cff87c97da5cca82c0f0891bc40602' },
        ],
        ['email without an @', { email: 'not-an-email' }, {}],
        [
            'hex-looking external ID',
            { external_id: 'A'.repeat(64) },
            { externalId: 'd53eda7a637c99cc7fb566d96e9fa109bf15c478410a3f5eb4d4c4e26cd081f6' },
        ],
        [
            'formatted phone',
            { phone: '+1 (425) 555-1234' },
            { ph: 'c59475d96e9f01d7d18d06cfad84dd02333207f02c0c2c5663ef2782cda0390e' },
        ],
        [
            'phone with 00 prefix',
            { phone: '0044 20 7946 0000' },
            { ph: '543f9cda443b9c55ebcf8ab34b586f9dc34948776b73de02393c41d5f8edc356' },
        ],
        ['phone without a country code', { phone: '425 555 1234' }, {}],
        [
            'msclkid with hyphens',
            { msclkid: 'dd4afccc-b1c9-4a4c-ad95-44dd7e5006ab' },
            { msclkid: 'dd4afcccb1c94a4cad9544dd7e5006ab' },
        ],
    ])('normalizes %s', async (_, personProperties, expectedUserData) => {
        const response = await tester.invokeMapping(
            'Conversion',
            { tagId: '12345678', apiToken: 'api-token', eventName: 'purchase' },
            createAdDestinationPayload({
                person: {
                    properties: {
                        msclkid: null,
                        email: null,
                        phone: null,
                        external_id: 'user-123',
                        ...personProperties,
                    },
                },
            })
        )
        expect(response.error).toBeUndefined()
        const body = parseJSON((response.invocation.queueParameters as { body: string }).body)
        expect(body.data[0].userData).toEqual({
            externalId: 'fcdec6df4d44dbc637c7c5b58efface52a7f8a88535423430255be0bb89bedd8',
            ...expectedUserData,
        })
        expect(JSON.stringify(response.logs)).not.toContain('425')
    })
    const phWarning = {
        index: 0,
        propertyName: 'data[0].userData.ph',
        attemptedValue: 'attempted-value',
        errorMessage: "'ph' must be a valid SHA256 string.",
        errorCode: 'InvalidSha256',
        isWarning: true,
    }
    const eventTimeError = {
        index: 0,
        propertyName: 'data[0].eventTime',
        attemptedValue: 'attempted-value',
        errorMessage: "'eventTime' must be a valid UNIX UTC timestamp in seconds within last 7 days.",
        errorCode: 'InvalidEventTime',
        isWarning: false,
    }
    it.each([
        [
            'logs a warning without the attempted value when a field is dropped',
            { status: 200, body: { eventsReceived: 1, error: { code: 'ValidationError', details: [phWarning] } } },
            undefined,
            ["Microsoft accepted the conversion without `data[0].userData.ph`: 'ph' must be a valid SHA256 string."],
        ],
        [
            'reports validation errors without the attempted value',
            {
                status: 400,
                body: { eventsReceived: 0, error: { code: 'ValidationError', details: [eventTimeError, phWarning] } },
            },
            "Error from capi.uet.microsoft.com (status 400): data[0].eventTime: 'eventTime' must be a valid UNIX UTC timestamp in seconds within last 7 days.; data[0].userData.ph: 'ph' must be a valid SHA256 string.",
            [],
        ],
    ])('%s', async (_, fetchResult, expectedError, expectedLogs) => {
        const response = await tester.invokeMapping(
            'Conversion',
            { tagId: '12345678', apiToken: 'api-token', eventName: 'purchase' },
            createAdDestinationPayload()
        )
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, fetchResult)
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toEqual(expectedError)
        expect(
            fetchResponse.logs
                .filter((log) => log.level === 'info' && !log.message.startsWith('Function completed'))
                .map((log) => log.message)
        ).toEqual(expectedLogs)
        expect(JSON.stringify(fetchResponse.logs)).not.toContain('attempted-value')
    })
})
