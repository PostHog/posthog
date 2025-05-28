import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './incoming_webhook.template'

describe('incoming webhook template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate())
    })

    it('should invoke the function', async () => {
        const response = await tester.invoke(
            {
                event: '{body.eventName}',
                distinct_id: 'hardcoded',
                properties: {
                    root_level: '{body.rootLevel}',
                    nested_level: '{body.nested.nestedLevel}',
                    missing: '{body.missing?.missingvalue}',
                },
            },
            {
                // TODO: Fix typing
                body: {
                    eventName: 'the event',
                    rootLevel: 'rootLevelValue',
                    nested: {
                        nestedLevel: 'nestedLevelValue',
                    },
                },
                headers: {},
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
                event: '{body.eventName}',
                distinct_id: 'hardcoded',
                auth_header: 'Bearer my-secret-token',
            },
            {
                body: {
                    eventName: 'the event',
                },
                headers: {
                    authorization: 'Bearer wrong-token',
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
                event: '{body.eventName}',
                distinct_id: 'hardcoded',
                auth_header: 'Bearer my-secret-token',
            },
            {
                body: {
                    eventName: 'the event',
                },
                headers: {
                    authorization: 'Bearer my-secret-token',
                },
            }
        )

        expect(response.capturedPostHogEvents).toHaveLength(1)

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.execResult).toBeNull()
    })
})
