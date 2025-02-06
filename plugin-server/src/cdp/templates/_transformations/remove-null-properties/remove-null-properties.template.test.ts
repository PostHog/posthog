import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './remove-null-properties.template'

describe('remove-null-properties.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should remove null properties from event', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    validProp: 'value',
                    nullProp: null,
                    anotherValidProp: 123,
                    anotherNullProp: null,
                },
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                validProp: 'value',
                anotherValidProp: 123,
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

    it('should handle event with all null properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    prop1: null,
                    prop2: null,
                    prop3: null,
                },
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
                    emptyArray: [],
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
                emptyArray: [],
                emptyObject: {},
            },
        })
    })

    it('should handle complex nested properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    object: { valid: 'value', nullProp: null },
                    array: [1, null, 3],
                    nullObject: null,
                    validNumber: 42,
                },
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                object: { valid: 'value', nullProp: null },
                array: [1, null, 3],
                validNumber: 42,
            },
        })
    })
})
