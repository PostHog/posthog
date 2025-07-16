import { DateTime } from 'luxon'

import { createHogExecutionGlobals } from '../_tests/fixtures'
import { formatHogInput } from './hog-inputs.service'

describe('Hog Inputs', () => {
    jest.setTimeout(1000)

    beforeEach(() => {
        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
    })

    describe('formatInput', () => {
        it('can handle null values in input objects', async () => {
            const globals = {
                ...createHogExecutionGlobals({
                    event: {
                        event: 'test',
                        uuid: 'test-uuid',
                    } as any,
                }),
                inputs: {},
            }

            // Body with null values that should be preserved
            const inputWithNulls = {
                body: {
                    value: {
                        event: '{event}',
                        person: null,
                        userId: null,
                    },
                },
            }

            // Call formatInput directly to test that it handles null values
            const result = await formatHogInput(inputWithNulls, globals)

            // Verify that null values are preserved
            expect(result.body.value.person).toBeNull()
            expect(result.body.value.userId).toBeNull()
            expect(result.body.value.event).toBe('{event}')
        })

        it('can handle deep null and undefined values', async () => {
            const globals = {
                ...createHogExecutionGlobals({
                    event: {
                        event: 'test',
                        uuid: 'test-uuid',
                    } as any,
                }),
                inputs: {},
            }

            const complexInput = {
                body: {
                    value: {
                        data: {
                            first: null,
                            second: undefined,
                            third: {
                                nested: null,
                            },
                        },
                    },
                },
            }

            const result = await formatHogInput(complexInput, globals)

            // Verify all null and undefined values are properly preserved
            expect(result.body.value.data.first).toBeNull()
            expect(result.body.value.data.second).toBeUndefined()
            expect(result.body.value.data.third.nested).toBeNull()
        })
    })
})
