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
                    $email: '$email',
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
                    Email: 'properties.nonexistent',
                    Phone: 'properties.user.phone',
                    Ssn: 'properties.deeply.nested.invalid.path',
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
})
