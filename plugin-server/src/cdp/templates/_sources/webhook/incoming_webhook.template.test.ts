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
                    body: {
                        eventName: 'the event',
                        rootLevel: 'rootLevelValue',
                        nested: {
                            nestedLevel: 'nestedLevelValue',
                        },
                    },
                    headers: {},
                    ip: '127.0.0.1',
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
                    body: {
                        eventName: 'the event',
                    },
                    headers: {
                        authorization: 'Bearer wrong-token',
                    },
                    ip: '127.0.0.1',
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
                    body: {
                        eventName: 'the event',
                    },
                    headers: {
                        authorization: 'Bearer my-secret-token',
                    },
                    ip: '127.0.0.1',
                },
            }
        )

        expect(response.capturedPostHogEvents).toHaveLength(1)

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.execResult).toBeNull()
    })

    it('should print the request body if debug is true', async () => {
        const response = await tester.invoke(
            {
                event: '{request.body.eventName}',
                distinct_id: 'hardcoded',
                debug: true,
            },
            {
                request: {
                    body: {
                        eventName: 'the event',
                    },
                    headers: {},
                },
            }
        )

        expect(response.logs.map((x) => x.message)).toEqual([
            `Incoming request:, {"eventName":"the event"}`,
            expect.stringContaining('Function completed'),
        ])
    })
})
