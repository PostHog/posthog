import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './pixel.template'

describe('pixel template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    const GOOD_RESPONSE = {
        httpResponse: {
            contentType: 'image/gif',
            body: 'R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==',
            isBase64Encoded: true,
            status: 200,
        },
    }

    it('should respond with a 1x1 pixel and keep credentials out of the event and the log', async () => {
        const response = await tester.invoke(
            {
                event: '{request.query.ph_event}',
                distinct_id: 'hardcoded',
                properties: { query_params: '{request.query}' },
                debug: true,
            },
            {
                request: {
                    method: 'GET',
                    body: {},
                    stringBody: '',
                    headers: {},
                    query: {
                        ph_event: 'the event',
                        other: 'other',
                        params: '2',
                        api_key: 'secret-key',
                        'x-api-key': 'secret-dashed',
                        access_token: 'secret-token',
                    },
                    ip: '127.0.0.1',
                },
            }
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.capturedPostHogEvents).toMatchInlineSnapshot(
            `
            [
              {
                "distinct_id": "hardcoded",
                "event": "the event",
                "properties": {
                  "$hog_function_execution_count": 1,
                  "query_params": {
                    "other": "other",
                    "params": "2",
                    "ph_event": "the event",
                  },
                },
                "team_id": 1,
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `
        )
        expect(response.logs.map((x) => x.message)).toEqual([
            `Incoming request:, {"ph_event":"the event","other":"other","params":"2"}`,
            expect.stringContaining('Function completed'),
        ])
        expect(response.execResult).toEqual(GOOD_RESPONSE)
    })

    it.each([
        ['api_key'],
        ['X-API-Key'],
        ['access_token'],
        ['accessToken'],
        ['refresh-token'],
        ['clientSecret'],
        ['client_secret'],
        ['Token'],
        ['signature'],
        ['has_password'],
        ['account[password]'],
        ['account[token]'],
        ['private_key'],
        ['aws_secret_access_key'],
        ['AWS-Secret-Access-Key'],
    ])('drops the credential key %s from the captured query', async (key) => {
        const response = await tester.invoke(
            { event: 'the event', distinct_id: 'hardcoded', properties: { query_params: '{request.query}' } },
            {
                request: {
                    method: 'GET',
                    body: {},
                    stringBody: '',
                    headers: {},
                    query: { utm_source: 'newsletter', [key]: 'secret-value' },
                    ip: '127.0.0.1',
                },
            }
        )
        expect(response.capturedPostHogEvents[0].properties.query_params).toEqual({ utm_source: 'newsletter' })
    })

    it.each([
        ['tokens_used'],
        ['total_tokens'],
        ['api_key_hint'],
        ['api_key_status'],
        ['apiXkey'],
        ['password_reset'],
        ['reset_token_id'],
        ['top_secret_sale'],
        ['isToken'],
        ['designToken'],
        ['monkey'],
    ])('keeps the look-alike key %s in the captured query', async (key) => {
        const response = await tester.invoke(
            { event: 'the event', distinct_id: 'hardcoded', properties: { query_params: '{request.query}' } },
            {
                request: {
                    method: 'GET',
                    body: {},
                    stringBody: '',
                    headers: {},
                    query: { utm_source: 'newsletter', [key]: 'kept-value' },
                    ip: '127.0.0.1',
                },
            }
        )
        expect(response.capturedPostHogEvents[0].properties.query_params).toEqual({
            utm_source: 'newsletter',
            [key]: 'kept-value',
        })
    })

    it('should respond with pixel even if event cannot be parsed', async () => {
        const response = await tester.invoke(
            {
                event: '{request.query.ph_event}',
                distinct_id: 'hardcoded',
            },
            {
                request: {
                    method: 'GET',
                    body: {},
                    stringBody: '',
                    headers: {},
                    query: {},
                    ip: '127.0.0.1',
                },
            }
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.capturedPostHogEvents).toEqual([])
        expect(response.logs.map((x) => x.message)).toEqual([
            'No event captured because the event name or the distinct ID is empty. By default they come from the ph_event and ph_distinct_id query parameters.',
            expect.stringContaining('Function completed'),
        ])
        expect(response.execResult).toEqual(GOOD_RESPONSE)
    })
})
