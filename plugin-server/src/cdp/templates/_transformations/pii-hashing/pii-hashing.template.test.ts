import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './pii-hashing.template'

interface EventResult {
    properties: {
        [key: string]: any
    }
}

describe('pii-hashing.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should hash property values', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $email: 'test@example.com',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToHash: {
                    Email: '$email',
                },
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as EventResult).properties.$email).toMatch(/^[a-f0-9]{64}$/)
        expect((response.execResult as EventResult).properties.$email).not.toBe('test@example.com')
    })

    it('should handle multiple properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $email: 'test@example.com',
                    $phone: '+1234567890',
                    safe_property: 'keep-me',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToHash: {
                    Email: '$email',
                    Phone: '$phone',
                },
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as EventResult).properties.$email).toMatch(/^[a-f0-9]{64}/)
        expect((response.execResult as EventResult).properties.$phone).toMatch(/^[a-f0-9]{64}/)
        expect((response.execResult as EventResult).properties.safe_property).toBe('keep-me')
    })

    it('should handle empty values gracefully', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    safe_property: 'keep-me',
                    $email: undefined,
                    $phone: undefined,
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToHash: {
                    Email: '$email',
                    Phone: '$phone',
                },
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as EventResult).properties.safe_property).toBe('keep-me')
        expect((response.execResult as EventResult).properties.$email).toBeUndefined()
        expect((response.execResult as EventResult).properties.$phone).toBeUndefined()
    })

    it('should handle empty propertiesToHash dictionary', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $email: 'test@example.com',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToHash: {},
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as EventResult).properties.$email).toBe('test@example.com')
    })

    it('should handle invalid property paths gracefully', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $email: 'test@example.com',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToHash: {
                    Email: 'nonexistent',
                    Phone: 'user.phone',
                    Ssn: 'deeply.nested.invalid.path',
                },
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        // Original properties should remain unchanged
        expect((response.execResult as EventResult).properties.$email).toBe('test@example.com')
        // Invalid paths should not create new properties
        expect((response.execResult as EventResult).properties.$phone).toBeUndefined()
        expect((response.execResult as EventResult).properties.$ssn).toBeUndefined()
    })

    it('should handle nested property paths', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $set: {
                        $ip: '127.0.0.1',
                        $email: 'test@example.com',
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToHash: {
                    ip: '$set.$ip',
                    email: '$set.$email',
                },
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as EventResult).properties.$set.$ip).toMatch(/^[a-f0-9]{64}$/)
        expect((response.execResult as EventResult).properties.$set.$email).toMatch(/^[a-f0-9]{64}$/)
    })

    it('should handle deeply nested property paths', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    user: {
                        contact: {
                            $email: 'test@example.com',
                            $phone: '+1234567890',
                        },
                    },
                    $set: {
                        profile: {
                            ssn: '123-45-6789',
                        },
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToHash: {
                    Email: 'user.contact.$email',
                    Phone: 'user.contact.$phone',
                    SSN: '$set.profile.ssn',
                },
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.properties.user.contact.$email).toMatch(/^[a-f0-9]{64}$/)
        expect(result.properties.user.contact.$phone).toMatch(/^[a-f0-9]{64}$/)
        expect(result.properties.$set.profile.ssn).toMatch(/^[a-f0-9]{64}$/)

        // Verify original values were hashed
        expect(result.properties.user.contact.$email).not.toBe('test@example.com')
        expect(result.properties.user.contact.$phone).not.toBe('+1234567890')
        expect(result.properties.$set.profile.ssn).not.toBe('123-45-6789')
    })

    it('should handle nonexistent nested paths gracefully', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    user: {
                        email: 'test@example.com',
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToHash: {
                    Email: 'user.contact.email', // nonexistent nested path
                },
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        // Should not modify anything when path doesn't exist
        const result = response.execResult as EventResult
        expect(result.properties.user.email).toBe('test@example.com')
        expect(result.properties.user.contact).toBeUndefined()
    })
})
