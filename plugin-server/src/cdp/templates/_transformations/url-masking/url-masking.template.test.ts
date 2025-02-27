import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './url-masking.template'

describe('url-masking.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should mask sensitive parameters in URLs', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com?email=test@example.com&password=secret&name=john',
                    $referrer: 'https://other.com?token=12345&email=test@example.com',
                },
            },
        })

        const response = await tester.invoke(
            {
                urlProperties: {
                    $current_url: 'email, password',
                    $referrer: 'email, token',
                },
                maskWith: '[REDACTED]',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                $current_url: 'https://example.com?email=[REDACTED]&password=[REDACTED]&name=john',
                $referrer: 'https://other.com?token=[REDACTED]&email=[REDACTED]',
            },
        })
    })

    it('should handle URLs without query parameters', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com',
                },
            },
        })

        const response = await tester.invoke(
            {
                urlProperties: {
                    $current_url: 'email, password',
                },
                maskWith: '[REDACTED]',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                $current_url: 'https://example.com',
            },
        })
    })

    it('should handle malformed URLs starting with question mark', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: '?email=test@example.com',
                },
            },
        })

        const response = await tester.invoke(
            {
                urlProperties: {
                    $current_url: 'email',
                },
                maskWith: '[REDACTED]',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                $current_url: '?email=test@example.com',
            },
        })
    })

    it('should handle missing properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com?email=test@example.com',
                },
            },
        })

        const response = await tester.invoke(
            {
                urlProperties: {
                    $current_url: 'email',
                    $referrer: 'email', // $referrer doesn't exist in properties
                },
                maskWith: '[REDACTED]',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                $current_url: 'https://example.com?email=[REDACTED]',
            },
        })
    })

    it('should handle parameters without values', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com?email&token=123&password',
                },
            },
        })

        const response = await tester.invoke(
            {
                urlProperties: {
                    $current_url: 'email, password, token',
                },
                maskWith: '[REDACTED]',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                $current_url: 'https://example.com?email=[REDACTED]&token=[REDACTED]&password=[REDACTED]',
            },
        })
    })

    it('should handle empty parameter values', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com?email=&token=123',
                },
            },
        })

        const response = await tester.invoke(
            {
                urlProperties: {
                    $current_url: 'email, token',
                },
                maskWith: '[REDACTED]',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                $current_url: 'https://example.com?email=[REDACTED]&token=[REDACTED]',
            },
        })
    })
})
