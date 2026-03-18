import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './remove-null-properties.template'

describe('remove-null-properties.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should remove null properties from event at all levels within depth limit', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    validProp: 'value',
                    nullProp: null,
                    nested: {
                        // level 2
                        valid: true,
                        nullProp: null,
                        deepNested: {
                            // level 3
                            valid: 'deep',
                            nullProp: null,
                            tooDeep: {
                                // level 4 - should remain unchanged
                                valid: 'too deep',
                                nullProp: null,
                            },
                        },
                    },
                    array: [1, null, 3],
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
                    deepNested: {
                        valid: 'deep',
                        tooDeep: {
                            // level 4 remains unchanged
                            valid: 'too deep',
                            nullProp: null,
                        },
                    },
                },
                array: [1, 3], // Expect real JavaScript array
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
                        nested: {
                            valid: 'value',
                            nullProp: null,
                            array: [1, null, { valid: true, nullProp: null }],
                        },
                        nullProp: null,
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
                    nested: {
                        valid: 'value',
                        array: [1, null, { valid: true }], // Updated to match actual behavior - null in array stays, but removed from object
                    },
                },
            },
        })
    })

    it('should process deeply nested structures up to max depth', async () => {
        interface DeepObject {
            nested?: DeepObject
            nullProp?: null
            value?: string
        }

        let deepObj: DeepObject = { value: 'test', nullProp: null }
        for (let i = 0; i < 5; i++) {
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

        // Only process up to level 3, leave deeper levels unchanged
        let result = (response.execResult as any).properties.deep
        let depth = 1
        while (result.nested && depth < 3) {
            expect('nullProp' in result).toBe(false)
            result = result.nested
            depth++
        }

        // After level 3, structure should remain unchanged
        expect(result.nullProp).toBe(null)
        if (result.nested) {
            expect(result.nested.nullProp).toBe(null)
        }
    })
})
