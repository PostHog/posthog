import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-capture.template'

describe('posthog capture template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })
    it('should invoke the function', async () => {
        const response = await tester.invoke(
            {
                event: 'event-name',
                distinct_id: '{event.distinct_id}',
                properties: { foo: 'bar', modified: '{event.properties.$lib_version}.xxx' },
            },
            { event: { event: 'event-name', distinct_id: 'distinct-id', properties: { $lib_version: '1.0.0' } } }
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.capturedPostHogEvents).toMatchInlineSnapshot(
            `
            [
              {
                "distinct_id": "distinct-id",
                "event": "event-name",
                "properties": {
                  "$hog_function_execution_count": 1,
                  "foo": "bar",
                  "modified": "1.0.0.xxx",
                },
                "team_id": 1,
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `
        )
    })
})
