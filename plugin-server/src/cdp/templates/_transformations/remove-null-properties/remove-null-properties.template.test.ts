import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './remove-null-properties.template'

describe('remove-null-properties.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should remove null properties from event at all levels', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    validProp: 'value',
                    nullProp: null,
                    nested: {
                        valid: true,
                        nullProp: null,
                    },
                    array: { '1': 1, '2': null, '3': 3 },
                },
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                validProp: 'value',
                nested: {
                    valid: true,
                },
                array: [1, 3],
            },
        })
    })

    it('should handle event with no properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {},
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {},
        })
    })

    it('should preserve non-null falsy values', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    emptyString: '',
                    zero: 0,
                    false: false,
                    nullValue: null,
                    emptyObject: {},
                },
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                emptyString: '',
                zero: 0,
                false: false,
                emptyObject: {},
            },
        })
    })

    it('should handle deeply nested structures', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    deep: {
                        level1: {
                            level2: {
                                valid: 'value',
                                nullProp: null,
                                array: { '1': 1, '2': null, '3': { valid: true, nullProp: null } },
                            },
                            nullProp: null,
                        },
                    },
                },
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                deep: {
                    level1: {
                        level2: {
                            valid: 'value',
                            array: [1, { valid: true }],
                        },
                    },
                },
            },
        })
    })

    it('should return original event when max depth is reached', async () => {
        interface DeepObject {
            nested?: DeepObject
            nullProp?: null
            value?: string
        }

        let deepObj: DeepObject = { value: 'test' }
        for (let i = 0; i < 15; i++) {
            deepObj = { nested: deepObj, nullProp: null }
        }

        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    deep: deepObj,
                },
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        // Should match the original input exactly
        expect(response.execResult).toMatchObject(mockGlobals.event)
    })
})
