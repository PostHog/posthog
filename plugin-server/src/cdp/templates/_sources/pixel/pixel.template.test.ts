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
            body: expect.stringContaining('GIF'),
            status: 200,
        },
    }

    it('should respond with a 1x1 pixel', async () => {
        const response = await tester.invoke(
            {
                event: '{request.query.ph_event}',
                distinct_id: 'hardcoded',
                properties: { query_params: '{request.query}' },
            },
            {
                request: {
                    method: 'GET',
                    body: {},
                    stringBody: '',
                    headers: {},
                    query: { ph_event: 'the event', other: 'other', params: '2' },
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
        expect(response.execResult).toEqual(GOOD_RESPONSE)
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
        expect(response.execResult).toEqual(GOOD_RESPONSE)
    })
})
