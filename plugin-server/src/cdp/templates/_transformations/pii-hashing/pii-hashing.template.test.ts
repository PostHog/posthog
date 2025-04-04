import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './pii-hashing.template'

interface EventResult {
    distinct_id?: string
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
                propertiesToHash: '$email',
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
                propertiesToHash: '$email,$phone',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as EventResult).properties.$email).toMatch(/^[a-f0-9]{64}$/)
        expect((response.execResult as EventResult).properties.$phone).toMatch(/^[a-f0-9]{64}$/)
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
                propertiesToHash: '$email,$phone',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as EventResult).properties.safe_property).toBe('keep-me')
        expect((response.execResult as EventResult).properties.$email).toBeUndefined()
        expect((response.execResult as EventResult).properties.$phone).toBeUndefined()
    })

    it('should handle empty propertiesToHash array', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $email: 'test@example.com',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToHash: '',
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
                propertiesToHash: 'nonexistent,user.phone,deeply.nested.invalid.path',
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
                propertiesToHash: '$set.$ip,$set.$email',
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
                propertiesToHash: 'user.contact.$email,user.contact.$phone,$set.profile.ssn',
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
                propertiesToHash: 'user.contact.email', // nonexistent nested path
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

    it('should hash distinct_id when enabled', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: 'user123',
                properties: {
                    $email: 'test@example.com',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToHash: '$email',
                hashDistinctId: true,
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as EventResult).distinct_id).toMatch(/^[a-f0-9]{64}$/)
        expect((response.execResult as EventResult).distinct_id).not.toBe('user123')
    })

    it('should not hash distinct_id when disabled', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: 'user123',
                properties: {
                    $email: 'test@example.com',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToHash: '$email',
                hashDistinctId: false,
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect((response.execResult as EventResult).distinct_id).toBe('user123')
    })

    it('should hash values with salt when provided', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $email: 'test@example.com',
                },
            },
        })

        const response1 = await tester.invoke(
            {
                propertiesToHash: '$email',
                salt: 'mysalt123',
            },
            mockGlobals
        )

        const response2 = await tester.invoke(
            {
                propertiesToHash: '$email',
                salt: 'differentSalt',
            },
            mockGlobals
        )

        expect(response1.finished).toBe(true)
        expect(response2.finished).toBe(true)

        const hash1 = (response1.execResult as EventResult).properties.$email
        const hash2 = (response2.execResult as EventResult).properties.$email

        // Both should be valid hashes
        expect(hash1).toMatch(/^[a-f0-9]{64}$/)
        expect(hash2).toMatch(/^[a-f0-9]{64}$/)

        // Different salts should produce different hashes for the same value
        expect(hash1).not.toBe(hash2)
    })

    it('should hash distinct_id with salt', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: 'user123',
                properties: {},
            },
        })

        const response1 = await tester.invoke(
            {
                propertiesToHash: '',
                hashDistinctId: true,
                salt: 'salt1',
            },
            mockGlobals
        )

        const response2 = await tester.invoke(
            {
                propertiesToHash: '',
                hashDistinctId: true,
                salt: 'salt2',
            },
            mockGlobals
        )

        expect(response1.finished).toBe(true)
        expect(response2.finished).toBe(true)

        const hash1 = (response1.execResult as EventResult).distinct_id
        const hash2 = (response2.execResult as EventResult).distinct_id

        // Both should be valid hashes
        expect(hash1).toMatch(/^[a-f0-9]{64}$/)
        expect(hash2).toMatch(/^[a-f0-9]{64}$/)

        // Different salts should produce different hashes
        expect(hash1).not.toBe(hash2)
        // Original value should be hashed
        expect(hash1).not.toBe('user123')
        expect(hash2).not.toBe('user123')
    })

    it('should produce consistent hashes with the same salt', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                distinct_id: 'user123',
                properties: {
                    $email: 'test@example.com',
                },
            },
        })

        const response1 = await tester.invoke(
            {
                propertiesToHash: '$email',
                hashDistinctId: true,
                salt: 'same-salt',
            },
            mockGlobals
        )

        const response2 = await tester.invoke(
            {
                propertiesToHash: '$email',
                hashDistinctId: true,
                salt: 'same-salt',
            },
            mockGlobals
        )

        expect(response1.finished).toBe(true)
        expect(response2.finished).toBe(true)

        // Same salt should produce same hashes
        expect((response1.execResult as EventResult).distinct_id).toBe(
            (response2.execResult as EventResult).distinct_id
        )
        expect((response1.execResult as EventResult).properties.$email).toBe(
            (response2.execResult as EventResult).properties.$email
        )
    })
})
