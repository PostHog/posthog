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
                    $email: '{event.properties.$email}',
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
                    $email: '{event.properties.$email}',
                    $phone: '{event.properties.$phone}',
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
                    $email: '{event.properties.$email}',
                    $phone: '{event.properties.$phone}',
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
                    $email: '{event.properties.nonexistent}',
                    $phone: '{event.properties.user.phone}',
                    $ssn: '{event.properties.deeply.nested.invalid.path}',
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

    it('should handle various property names and paths', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $email: 'test@example.com',
                    regular_field: 'sensitive-data',
                    custom_field: 'another-secret',
                },
            },
        })

        const response = await tester.invoke(
            {
                propertiesToHash: {
                    regular_field: '{event.properties.regular_field}',
                    custom_field: '{event.properties.$email}', // Map to different source
                    $email: '{event.properties.custom_field}', // Cross-property mapping
                },
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        // Check each property is hashed
        expect((response.execResult as EventResult).properties.regular_field).toMatch(/^[a-f0-9]{64}$/)
        expect((response.execResult as EventResult).properties.custom_field).toMatch(/^[a-f0-9]{64}$/)
        expect((response.execResult as EventResult).properties.$email).toMatch(/^[a-f0-9]{64}$/)
        // Verify original values are not present
        expect((response.execResult as EventResult).properties.regular_field).not.toBe('sensitive-data')
        expect((response.execResult as EventResult).properties.custom_field).not.toBe('test@example.com')
        expect((response.execResult as EventResult).properties.$email).not.toBe('another-secret')
    })
})
