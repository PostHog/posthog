import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-group-identify.template'

describe('posthog group identify template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })
    it('should invoke the function', async () => {
        const response = await tester.invoke(
            {
                group_type: 'organization',
                group_key: 'posthog.com',
                group_properties: { latest_event: '{event.event}' },
            },
            { event: { event: 'event-name', distinct_id: 'distinct-id', properties: {} } }
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.capturedPostHogEvents).toMatchInlineSnapshot(
            `
            [
              {
                "distinct_id": "organization_posthog.com",
                "event": "$groupidentify",
                "properties": {
                  "$group_key": "posthog.com",
                  "$group_set": {
                    "latest_event": "event-name",
                  },
                  "$group_type": "organization",
                  "$hog_function_execution_count": 1,
                },
                "team_id": 1,
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `
        )
    })
    it('should return an error if group_type is not provided', async () => {
        const response = await tester.invoke(
            {
                group_key: 'posthog.com',
                group_type: '{event.properties.missing}',
                group_properties: { latest_event: '{event.event}' },
            },
            { event: { event: 'event-name', distinct_id: 'distinct-id', properties: {} } }
        )
        expect(response.error).toMatchInlineSnapshot(`"Group type is required"`)
    })
    it('should return an error if group_key is not provided', async () => {
        const response = await tester.invoke(
            {
                group_key: '{event.properties.missing}',
                group_type: 'organization',
                group_properties: { latest_event: '{event.event}' },
            },
            { event: { event: 'event-name', distinct_id: 'distinct-id', properties: {} } }
        )
        expect(response.error).toMatchInlineSnapshot(`"Group key is required"`)
    })
})
