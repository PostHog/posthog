import { DateTime } from 'luxon'

import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import { createHogExecutionGlobals, createHogFunction } from '../_tests/fixtures'
import { cloneInvocation, createInvocation } from './invocation-utils'

describe('Invocation utils', () => {
    describe('cloneInvocation', () => {
        beforeEach(() => {
            const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
            jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        const invocation = createInvocation(
            {
                ...createHogExecutionGlobals(),
                inputs: { foo: 'bar' },
            },
            createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.elements_href_filter,
            })
        )

        invocation.queueSource = 'postgres'

        it('should clone an invocation', () => {
            const cloned = cloneInvocation(invocation)
            const { id, state, hogFunction, functionId, ...rest } = cloned
            expect(id).toBe(invocation.id)
            expect(functionId).toBe(invocation.functionId)
            expect(state).toBe(invocation.state)
            expect(hogFunction).toBe(invocation.hogFunction)

            expect(rest).toMatchInlineSnapshot(`
                {
                  "queue": "hog",
                  "queueMetadata": undefined,
                  "queueParameters": undefined,
                  "queuePriority": 0,
                  "queueScheduledAt": undefined,
                  "queueSource": "postgres",
                  "teamId": 1,
                }
            `)
        })

        it('should allow overriding properties', () => {
            const cloned = cloneInvocation(invocation, {
                queuePriority: 1,
                queueMetadata: { foo: 'bar' },
                queueScheduledAt: DateTime.utc(),
                queueParameters: {
                    type: 'fetch',
                    url: 'https://example.com',
                    method: 'GET',
                },
            })

            const { id, state, hogFunction, functionId, ...rest } = cloned
            expect(id).toBe(invocation.id)
            expect(functionId).toBe(invocation.functionId)
            expect(state).toBe(invocation.state)
            expect(hogFunction).toBe(invocation.hogFunction)

            expect(rest).toMatchInlineSnapshot(`
                {
                  "queue": "hog",
                  "queueMetadata": {
                    "foo": "bar",
                  },
                  "queueParameters": {
                    "method": "GET",
                    "type": "fetch",
                    "url": "https://example.com",
                  },
                  "queuePriority": 1,
                  "queueScheduledAt": "2025-01-01T00:00:00.000Z",
                  "queueSource": "postgres",
                  "teamId": 1,
                }
            `)
        })
    })
})
