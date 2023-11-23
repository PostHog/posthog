import { EventType } from '@rrweb/types'

import { TransformationError, validateAgainstWebSchema, validateFromMobile } from './index'

describe('validation', () => {
    test('example of validating incoming _invalid_ data', () => {
        const invalidData = {
            foo: 'abc',
            bar: 'abc',
        }

        expect(validateFromMobile(invalidData).isValid).toBe(false)
    })

    test('example of validating mobile meta event', () => {
        const validData = {
            data: { width: 1, height: 1 },
            timestamp: 1,
            type: EventType.Meta,
        }

        expect(validateFromMobile(validData)).toStrictEqual({
            isValid: true,
            errors: null,
        })
    })

    describe('validate web schema', () => {
        test('should be invalid if...', () => {
            expect(() => validateAgainstWebSchema({})).toThrow(TransformationError)
        })

        test('should be valid when...', () => {
            expect(validateAgainstWebSchema({ data: {}, timestamp: 12345, type: 0 })).toBeTruthy()
        })
    })
})
