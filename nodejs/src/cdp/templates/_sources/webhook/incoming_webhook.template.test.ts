import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './incoming_webhook.template'

describe('incoming webhook template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('should invoke the function', async () => {
        const response = await tester.invoke(
            {
                event: '{request.body.eventName}',
                distinct_id: 'hardcoded',
                properties: {
                    root_level: '{request.body.rootLevel}',
                    nested_level: '{request.body.nested.nestedLevel}',
                    missing: '{request.body.missing?.missingvalue}',
                },
            },
            {
                request: {
                    method: 'POST',
                    body: {
                        eventName: 'the event',
                        rootLevel: 'rootLevelValue',
                        nested: {
                            nestedLevel: 'nestedLevelValue',
                        },
                    },
                    stringBody: '',
                    headers: {},
                    ip: '127.0.0.1',
                    query: {},
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)

        expect(response.capturedPostHogEvents).toMatchInlineSnapshot(`
            [
              {
                "distinct_id": "hardcoded",
                "event": "the event",
                "properties": {
                  "$hog_function_execution_count": 1,
                  "missing": null,
                  "nested_level": "nestedLevelValue",
                  "root_level": "rootLevelValue",
                },
                "team_id": 1,
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `)
    })

    it('should return 401 if the auth header is incorrect', async () => {
        const response = await tester.invoke(
            {
                event: '{request.body.eventName}',
                distinct_id: 'hardcoded',
                auth_header: 'Bearer my-secret-token',
            },
            {
                request: {
                    method: 'POST',
                    body: {
                        eventName: 'the event',
                    },
                    stringBody: '',
                    headers: {
                        authorization: 'Bearer wrong-token',
                    },
                    ip: '127.0.0.1',
                    query: {},
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)

        expect(response.execResult).toEqual({
            httpResponse: {
                status: 401,
                body: 'Unauthorized',
            },
        })
    })

    it('should pass if the auth header is correct', async () => {
        const response = await tester.invoke(
            {
                event: '{request.body.eventName}',
                distinct_id: 'hardcoded',
                auth_header: 'Bearer my-secret-token',
            },
            {
                request: {
                    method: 'POST',
                    body: {
                        eventName: 'the event',
                    },
                    stringBody: '',
                    headers: {
                        authorization: 'Bearer my-secret-token',
                    },
                    ip: '127.0.0.1',
                    query: {},
                },
            }
        )

        expect(response.capturedPostHogEvents).toHaveLength(1)

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.execResult).toBeUndefined()
    })

    it('should capture query parameters on a GET request', async () => {
        const response = await tester.invoke(
            {
                event: '{request.query.event}',
                distinct_id: '{request.query.distinct_id}',
                method: 'GET',
                properties: {
                    query_params: '{request.query}',
                },
            },
            {
                request: {
                    method: 'GET',
                    body: {},
                    stringBody: '',
                    headers: {},
                    ip: '127.0.0.1',
                    query: {
                        event: 'the event',
                        distinct_id: 'user-1',
                        utm_source: 'newsletter',
                    },
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)

        expect(response.capturedPostHogEvents).toMatchInlineSnapshot(`
            [
              {
                "distinct_id": "user-1",
                "event": "the event",
                "properties": {
                  "$hog_function_execution_count": 1,
                  "query_params": {
                    "distinct_id": "user-1",
                    "event": "the event",
                    "utm_source": "newsletter",
                  },
                },
                "team_id": 1,
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `)
    })

    it('captures the query on the default properties mapping, without the credential in it', async () => {
        // The mapping is left alone so the template's own default is what runs: the case above
        // passes its own properties and so cannot tell the default apart from a hand-written one.
        // A pixel authenticates in the query string, so the key arrives beside the real properties.
        const response = await tester.invoke(
            {
                event: '{request.query.event}',
                distinct_id: '{request.query.distinct_id}',
                method: 'GET',
            },
            {
                request: {
                    method: 'GET',
                    body: {},
                    stringBody: '',
                    headers: {},
                    ip: '127.0.0.1',
                    query: {
                        event: 'the event',
                        distinct_id: 'user-1',
                        utm_source: 'newsletter',
                        api_key: 'phc_secret',
                        Token: 'also-secret',
                        'x-api-key': 'dashed-secret',
                        client_secret: 'suffixed-secret',
                    },
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)

        const properties = response.capturedPostHogEvents[0].properties
        expect(properties.query_params).toEqual({
            event: 'the event',
            distinct_id: 'user-1',
            utm_source: 'newsletter',
        })
        expect(JSON.stringify(properties)).not.toContain('secret')
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
            {
                event: 'the event',
                distinct_id: 'hardcoded',
                method: 'GET',
                properties: { query_params: '{request.query}' },
            },
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
            {
                event: 'the event',
                distinct_id: 'hardcoded',
                method: 'GET',
                properties: { query_params: '{request.query}' },
            },
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

    it('should print the method, query, header names and body without credentials if debug is true', async () => {
        const response = await tester.invoke(
            {
                event: '{request.body.eventName}',
                distinct_id: 'hardcoded',
                debug: true,
            },
            {
                request: {
                    method: 'POST',
                    body: {
                        eventName: 'the event',
                        password: 'my-secret-password',
                    },
                    stringBody: '',
                    headers: {
                        authorization: 'Bearer my-secret-token',
                        'x-api-key': 'my-secret-key',
                    },
                    query: {
                        utm_source: 'newsletter',
                        token: 'my-secret-query-token',
                    },
                },
            }
        )

        expect(response.logs.map((x) => x.message)).toEqual([
            `Incoming request:, POST, query:, {"utm_source":"newsletter"}, header names:, ["authorization","x-api-key"], body:, {"eventName":"the event"}`,
            expect.stringContaining('Function completed'),
        ])
    })
})
