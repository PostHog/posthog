import crypto from 'crypto'

import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './hash-properties.template'

interface EventResult {
    distinct_id?: string
    properties: {
        [key: string]: any
        $set?: {
            [key: string]: any
        }
        $set_once?: {
            [key: string]: any
        }
    }
}

function sha256(data: string, salt = '1234567890'): string {
    return crypto
        .createHash('sha256')
        .update(data + salt)
        .digest('hex')
}

describe('hash-properties.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should hash private fields in event properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: '105338229',
                properties: {
                    userid: '105338229',
                    name: 'John Doe',
                    email: 'john@example.com',
                    safe_property: 'keep-me',
                },
            },
        })

        const response = await tester.invoke(
            {
                salt: '1234567890',
                privateFields: 'distinct_id,userid,name,email',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.distinct_id).toMatch(sha256('105338229'))
        expect(result.properties.userid).toMatch(sha256('105338229'))
        expect(result.properties.name).toMatch(sha256('John Doe'))
        expect(result.properties.email).toMatch(sha256('john@example.com'))
        expect(result.properties.safe_property).toBe('keep-me')

        // Verify original values were hashed
        expect(result.distinct_id).not.toBe('105338229')
        expect(result.properties.userid).not.toBe('105338229')
        expect(result.properties.name).not.toBe('John Doe')
        expect(result.properties.email).not.toBe('john@example.com')
    })

    it('should handle $set and $set_once properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: '105338229',
                properties: {
                    $set: {
                        userid: '105338229',
                        name: 'John Doe',
                    },
                    $set_once: {
                        initial_userid: '105338229',
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                salt: '1234567890',
                privateFields: 'distinct_id,userid,name,initial_userid',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.distinct_id).toMatch(sha256('105338229'))
        expect(result.properties.$set?.userid).toMatch(sha256('105338229'))
        expect(result.properties.$set?.name).toMatch(sha256('John Doe'))
        expect(result.properties.$set_once?.initial_userid).toMatch(sha256('105338229'))
    })

    it('should handle empty or missing fields gracefully', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: '105338229',
                properties: {
                    userid: '105338229',
                    name: undefined,
                    email: '',
                    safe_property: 'keep-me',
                },
            },
        })

        const response = await tester.invoke(
            {
                salt: '1234567890',
                privateFields: 'distinct_id,userid,name,email,nonexistent',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.distinct_id).toMatch(sha256('105338229'))
        expect(result.properties.userid).toMatch(sha256('105338229'))
        expect(result.properties.name).toBeUndefined()
        expect(result.properties.email).toBe('')
        expect(result.properties.safe_property).toBe('keep-me')
    })

    it('should handle non-string values', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: '105338229',
                properties: {
                    userid: 12345,
                    name: null,
                    email: 'john@example.com',
                    age: 30,
                },
            },
        })

        const response = await tester.invoke(
            {
                salt: '1234567890',
                privateFields: 'distinct_id,userid,name,email,age',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.distinct_id).toMatch(sha256('105338229'))
        expect(result.properties.userid).toBe(12345) // Non-string values should not be hashed
        expect(result.properties.name).toBe(null)
        expect(result.properties.email).toMatch(sha256('john@example.com'))
        expect(result.properties.age).toBe(30) // Non-string values should not be hashed
    })

    it('should handle empty privateFields string', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: '105338229',
                properties: {
                    userid: '105338229',
                    name: 'John Doe',
                },
            },
        })

        const response = await tester.invoke(
            {
                salt: '1234567890',
                privateFields: '',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.distinct_id).toBe('105338229')
        expect(result.properties.userid).toBe('105338229')
        expect(result.properties.name).toBe('John Doe')
    })

    it('should handle whitespace in privateFields', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: '105338229',
                properties: {
                    userid: '105338229',
                    name: 'John Doe',
                },
            },
        })

        const response = await tester.invoke(
            {
                salt: '1234567890',
                privateFields: ' distinct_id , userid , name ',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.distinct_id).toMatch(sha256('105338229'))
        expect(result.properties.userid).toMatch(sha256('105338229'))
        expect(result.properties.name).toMatch(sha256('John Doe'))
    })

    it('should produce consistent hashes with same salt', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: '105338229',
                properties: {
                    userid: '105338229',
                },
            },
        })

        const response1 = await tester.invoke(
            {
                salt: '1234567890',
                privateFields: 'distinct_id,userid',
            },
            mockGlobals
        )

        const response2 = await tester.invoke(
            {
                salt: '1234567890',
                privateFields: 'distinct_id,userid',
            },
            mockGlobals
        )

        expect(response1.finished).toBe(true)
        expect(response2.finished).toBe(true)
        expect(response1.error).toBeUndefined()
        expect(response2.error).toBeUndefined()

        const result1 = response1.execResult as EventResult
        const result2 = response2.execResult as EventResult

        expect(result1.distinct_id).toBe(result2.distinct_id)
        expect(result1.properties.userid).toBe(result2.properties.userid)
    })

    it('should produce different hashes with different salts', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: '105338229',
                properties: {
                    userid: '105338229',
                },
            },
        })

        const response1 = await tester.invoke(
            {
                salt: '1234567890',
                privateFields: 'distinct_id,userid',
            },
            mockGlobals
        )

        const response2 = await tester.invoke(
            {
                salt: 'different_salt',
                privateFields: 'distinct_id,userid',
            },
            mockGlobals
        )

        expect(response1.finished).toBe(true)
        expect(response2.finished).toBe(true)
        expect(response1.error).toBeUndefined()
        expect(response2.error).toBeUndefined()

        const result1 = response1.execResult as EventResult
        const result2 = response2.execResult as EventResult

        expect(result1.distinct_id).not.toBe(result2.distinct_id)
        expect(result1.properties.userid).not.toBe(result2.properties.userid)
    })

    it('should handle missing salt', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: '105338229',
                properties: {
                    userid: '105338229',
                },
            },
        })

        const response = await tester.invoke(
            {
                salt: '',
                privateFields: 'distinct_id,userid',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.distinct_id).toMatch(sha256('105338229', ''))
        expect(result.properties.userid).toMatch(sha256('105338229', ''))
    })

    it('should not hash $set and $set_once properties if includeSetProperties is false', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: '105338229',
                properties: {
                    userid: '105338229',
                    $set: {
                        userid: '105338229',
                    },
                    $set_once: {
                        initial_userid: '105338229',
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                salt: '1234567890',
                privateFields: 'distinct_id,userid',
                includeSetProperties: false,
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.properties).toMatchInlineSnapshot(`
            {
              "$set": {
                "userid": "105338229",
              },
              "$set_once": {
                "initial_userid": "105338229",
              },
              "userid": "83f029dcb4f5e8f260f008d71e770627adb92aa050aae0c005adad81cc57747c",
            }
        `)
    })
})
