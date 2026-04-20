import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-update-person-properties.template'

describe('posthog update person properties template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })
    it('should invoke the function', async () => {
        const response = await tester.invoke(
            {
                distinct_id: '{event.distinct_id}',
                set_properties: { foo: 'bar', modified: '{event.properties.$lib_version}.xxx' },
                set_once_properties: { latest_event: '{event.event}' },
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
                "event": "$set",
                "properties": {
                  "$hog_function_execution_count": 1,
                  "$set": {
                    "foo": "bar",
                    "modified": "1.0.0.xxx",
                  },
                  "$set_once": {
                    "latest_event": "event-name",
                  },
                },
                "team_id": 1,
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `
        )
    })
    it('should return an error if distinct_id is not provided', async () => {
        const response = await tester.invoke(
            {
                distinct_id: '{event.properties.missing}',
                set_properties: { foo: 'bar', modified: '{event.properties.$lib_version}.xxx' },
                set_once_properties: { latest_event: '{event.event}' },
            },
            { event: { event: 'event-name', distinct_id: 'distinct-id', properties: {} } }
        )
        expect(response.error).toMatchInlineSnapshot(`"Distinct ID is required"`)
    })
})
