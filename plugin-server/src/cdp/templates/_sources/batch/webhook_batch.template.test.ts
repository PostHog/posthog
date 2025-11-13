import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './webhook_batch.template'

describe('webhook batch template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('should invoke the function', async () => {
        const response = await tester.invoke(
            {
                actor_id: '{request.body.actor_id}',
                filters: {},
            },
            {
                request: {
                    method: 'POST',
                    body: {
                        actor_id: 'actor123',
                        filters: { key: 'value' },
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
                "distinct_id": "actor123",
                "event": "$workflow_batch_triggered",
                "properties": {
                  "filters": { "key": "value" },
                },
                "team_id": 1,
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `)
    })

    it('should return 400 if actor_id is missing', async () => {
        const response = await tester.invoke(
            {
                filters: {},
            },
            {
                request: {
                    method: 'POST',
                    body: {},
                    stringBody: '',
                    headers: {},
                    ip: '127.0.0.1',
                    query: {},
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)

        expect(response.execResult).toEqual({
            httpResponse: {
                status: 400,
                body: {
                    error: '"actor_id" could not be parsed correctly',
                },
            },
        })
    })
})
