import { createHash } from 'crypto'
import { DateTime, Settings } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester, createAdDestinationPayload } from '../../test/test-helpers'
import { template } from './google.template'

jest.setTimeout(60 * 1000)

describe('google template', () => {
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

    it('works with single product event', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            {
                oauth: {
                    access_token: 'access-token',
                },
                customerId: '1231231234/5675675678',
                conversionActionId: '123456789',
            },
            createAdDestinationPayload({
                event: {
                    properties: {
                        $current_url: 'https://posthog.com/merch?product=tactical-black-t-shirt',
                        currency: 'USD',
                        value: '100',
                        order_id: '1234567890',
                    },
                },
                person: {
                    properties: {
                        phone: '+1234567890',
                        external_id: '1234567890',
                        first_name: 'Max',
                        last_name: 'AI',
                    },
                },
            }),
            {
                currencyCode: '{event.properties.currency}',
                conversionValue: '{event.properties.value}',
                orderId: '{event.properties.order_id}',
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"conversions":[{"conversion_action":"customers/1231231234/conversionActions/123456789","conversion_date_time":"2025-01-01 00:00:00+00:00","gclid":"google-id","user_identifiers":[{"hashed_email":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3"}],"conversion_value":"100","currency_code":"USD","order_id":"1234567890"}],"partialFailure":true}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "login-customer-id": "5675675678",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://googleads.googleapis.com/v24/customers/1231231234:uploadClickConversions",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('works with empty properties', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            {
                oauth: {
                    access_token: 'access-token',
                },
                customerId: '1231231234/5675675678',
                conversionActionId: '123456789',
            },
            createAdDestinationPayload()
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"conversions":[{"conversion_action":"customers/1231231234/conversionActions/123456789","conversion_date_time":"2025-01-01 00:00:00+00:00","gclid":"google-id","user_identifiers":[{"hashed_email":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3"}]}],"partialFailure":true}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "login-customer-id": "5675675678",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://googleads.googleapis.com/v24/customers/1231231234:uploadClickConversions",
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
            'Conversion',
            {
                oauth: {
                    access_token: 'access-token',
                },
                customerId: '1231231234/5675675678',
                conversionActionId: '123456789',
                currencyCode: '{event.properties.currency}',
            },
            createAdDestinationPayload()
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"conversions":[{"conversion_action":"customers/1231231234/conversionActions/123456789","conversion_date_time":"2025-01-01 00:00:00+00:00","gclid":"google-id","user_identifiers":[{"hashed_email":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3"}]}],"partialFailure":true}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "login-customer-id": "5675675678",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://googleads.googleapis.com/v24/customers/1231231234:uploadClickConversions",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { status: 'Something went wrong', message: 'Invalid event properties' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from googleads.googleapis.com (status 400): {'status': 'Something went wrong', 'message': 'Invalid event properties'}"`
        )
    })

    it('falls back to hashed identifiers when gclid is missing', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            {
                oauth: {
                    access_token: 'access-token',
                },
                customerId: '1231231234/5675675678',
                conversionActionId: '123456789',
            },
            createAdDestinationPayload({
                person: {
                    properties: {
                        gclid: null,
                    },
                },
            }),
            {
                phone: '{person.properties.phone}',
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"conversions":[{"conversion_action":"customers/1231231234/conversionActions/123456789","conversion_date_time":"2025-01-01 00:00:00+00:00","user_identifiers":[{"hashed_email":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3"},{"hashed_phone_number":"422ce82c6fc1724ac878042f7d055653ab5e983d186e616826a72d4384b68af8"}]}],"partialFailure":true}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "login-customer-id": "5675675678",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://googleads.googleapis.com/v24/customers/1231231234:uploadClickConversions",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('skips when neither gclid nor user identifiers are present', async () => {
        const response = await tester.invokeMapping(
            'Conversion',
            {
                oauth: {
                    access_token: 'access-token',
                },
                customerId: '1231231234/5675675678',
                conversionActionId: '123456789',
            },
            createAdDestinationPayload({
                person: {
                    properties: {
                        gclid: null,
                        email: null,
                    },
                },
            })
        )

        expect(response.logs.filter((log) => log.level === 'info').map((log) => log.message)).toMatchInlineSnapshot(`
            [
              "No click ID or user identifiers. Skipping...",
            ]
        `)
        expect(response.finished).toEqual(true)
    })

    const sha256 = (value: string): string => createHash('sha256').update(value).digest('hex')

    const invokeConversion = (
        personProperties: Record<string, any>,
        mapping: Record<string, any> = {}
    ): ReturnType<TemplateTester['invokeMapping']> =>
        tester.invokeMapping(
            'Conversion',
            {
                oauth: { access_token: 'access-token' },
                customerId: '1231231234/5675675678',
                conversionActionId: '123456789',
            },
            createAdDestinationPayload({ person: { properties: personProperties } }),
            { phone: '{person.properties.phone}', ...mapping }
        )

    const sentConversion = (invocation: any): Record<string, any> =>
        parseJSON(invocation.queueParameters.body).conversions[0]

    const partialFailure = (...codes: string[]): Record<string, any> => ({
        partialFailureError: {
            message: codes.join(', '),
            details: [{ errors: codes.map((code) => ({ errorCode: { conversionUploadError: code } })) }],
        },
    })

    it.each([
        ['gclid only', { gclid: 'g1' }, { gclid: 'g1' }],
        ['gclid and gbraid', { gclid: 'g1', gbraid: 'b1' }, { gclid: 'g1', gbraid: 'b1' }],
        ['gclid and wbraid', { gclid: 'g1', wbraid: 'w1' }, { gclid: 'g1' }],
        ['gbraid and wbraid', { gclid: null, gbraid: 'b1', wbraid: 'w1' }, { gbraid: 'b1' }],
        ['wbraid only', { gclid: null, wbraid: 'w1' }, { wbraid: 'w1' }],
        [
            '$initial_ fallbacks',
            { gclid: null, $initial_gclid: 'g0', $initial_gbraid: 'b0' },
            { gclid: 'g0', gbraid: 'b0' },
        ],
    ])('sends a valid click ID combination for %s', async (_, properties, expected) => {
        const response = await invokeConversion(properties)

        const conversion = sentConversion(response.invocation)
        expect({ gclid: conversion.gclid, gbraid: conversion.gbraid, wbraid: conversion.wbraid }).toEqual({
            gclid: undefined,
            gbraid: undefined,
            wbraid: undefined,
            ...expected,
        })
    })

    it.each([
        ['trims and lowercases email', { email: '  Jane.Doe@Example.COM ' }, { hashed_email: 'jane.doe@example.com' }],
        [
            'drops gmail dots but keeps plus',
            { email: 'Jane.Doe+ads@gmail.com' },
            { hashed_email: 'janedoe+ads@gmail.com' },
        ],
        ['omits a malformed email', { email: 'not-an-email' }, {}],
        ['strips phone separators', { phone: '+1 (425) 555-1234' }, { hashed_phone_number: '+14255551234' }],
        ['converts a 00 prefix', { phone: '0044 20 7946 0958' }, { hashed_phone_number: '+442079460958' }],
        ['adds a missing plus', { phone: '14255551234' }, { hashed_phone_number: '+14255551234' }],
        ['omits a domestic number', { phone: '020 7946 0958' }, {}],
    ])('normalizes user identifiers before hashing: %s', async (_, properties, expected) => {
        const response = await invokeConversion({ gclid: 'g1', email: null, phone: null, ...properties })

        const identifiers = sentConversion(response.invocation).user_identifiers ?? []
        expect(Object.assign({}, ...identifiers)).toEqual(
            Object.fromEntries(Object.entries(expected).map(([key, value]) => [key, sha256(value)]))
        )
    })

    it.each(['EXPIRED_EVENT', 'UNPARSEABLE_GBRAID', 'INVALID_CUSTOMER_FOR_CLICK', 'UNAUTHORIZED_CUSTOMER'])(
        'retries once with hashed identifiers only when Google rejects the click ID with %s',
        async (code) => {
            const response = await invokeConversion({ gclid: 'g1', gbraid: 'b1' })
            const retry = await tester.invokeFetchResponse(response.invocation, {
                status: 200,
                body: partialFailure(code),
            })

            expect(retry.finished).toBe(false)
            const conversion = sentConversion(retry.invocation)
            expect(conversion.gclid).toBeUndefined()
            expect(conversion.gbraid).toBeUndefined()
            expect(conversion.user_identifiers).toEqual(sentConversion(response.invocation).user_identifiers)

            const done = await tester.invokeFetchResponse(retry.invocation, { status: 200, body: { results: [{}] } })
            expect(done.finished).toBe(true)
            expect(done.error).toBeUndefined()
        }
    )

    it.each(['INVALID_USER_IDENTIFIER', 'CUSTOMER_NOT_ACCEPTED_CUSTOMER_DATA_TERMS'])(
        'retries once with the click ID only when Google rejects the hashed email/phone with %s',
        async (code) => {
            const response = await invokeConversion({ gclid: 'g1', gbraid: 'b1' })
            const retry = await tester.invokeFetchResponse(response.invocation, {
                status: 200,
                body: partialFailure(code),
            })

            expect(retry.finished).toBe(false)
            const conversion = sentConversion(retry.invocation)
            expect(conversion.user_identifiers).toBeUndefined()
            expect({ gclid: conversion.gclid, gbraid: conversion.gbraid }).toEqual({ gclid: 'g1', gbraid: 'b1' })

            const done = await tester.invokeFetchResponse(retry.invocation, { status: 200, body: { results: [{}] } })
            expect(done.finished).toBe(true)
            expect(done.error).toBeUndefined()
        }
    )

    it.each([
        ['a click ID rejection without user identifiers', { gclid: 'g1', email: null, phone: null }, ['EXPIRED_EVENT']],
        ['a click ID rejection mixed with another error', {}, ['EXPIRED_EVENT', 'NO_CONVERSION_ACTION_FOUND']],
        ['a user data rejection without a click ID', { gclid: null }, ['INVALID_USER_IDENTIFIER']],
        ['both the click ID and the user data rejected', {}, ['EXPIRED_EVENT', 'INVALID_USER_IDENTIFIER']],
        ['a non click ID error', {}, ['TOO_RECENT_EVENT']],
    ])('fails without retrying on %s', async (_, properties, codes) => {
        const response = await invokeConversion(properties)
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: partialFailure(...codes),
        })

        expect(result.finished).toBe(true)
        expect(result.error).toEqual(`Error from googleads.googleapis.com (status 200): ${codes.join(', ')}`)
    })

    it('fails when the hashed retry is also rejected', async () => {
        const response = await invokeConversion({})
        const retry = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: partialFailure('EXPIRED_EVENT'),
        })
        const result = await tester.invokeFetchResponse(retry.invocation, {
            status: 200,
            body: partialFailure('CUSTOMER_NOT_ACCEPTED_CUSTOMER_DATA_TERMS'),
        })

        expect(result.finished).toBe(true)
        expect(result.error).toEqual(
            'Error from googleads.googleapis.com (status 200): CUSTOMER_NOT_ACCEPTED_CUSTOMER_DATA_TERMS'
        )
    })

    it.each([
        [
            'CLICK_NOT_FOUND',
            'Google could not match the hashed email/phone to an ad click. The conversion was not recorded.',
        ],
        ['ORDER_ID_ALREADY_IN_USE', 'Google already recorded this conversion. Skipping...'],
    ])('logs %s without failing', async (code, message) => {
        const response = await invokeConversion({ gclid: null })
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: partialFailure(code),
        })

        expect(result.finished).toBe(true)
        expect(result.error).toBeUndefined()
        expect(result.logs.map((log) => log.message)).toContain(message)
    })
})
