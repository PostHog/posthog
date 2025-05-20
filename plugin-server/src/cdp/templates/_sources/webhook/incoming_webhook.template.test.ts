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
                body: {
                    eventName: 'the event',
                    rootLevel: 'rootLevelValue',
                    nested: {
                        nestedLevel: 'nestedLevelValue',
                    },
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
})
