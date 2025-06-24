import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './url-normalization.template'

interface EventResult {
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

describe('url-normalization.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    const commonInputs = {
        removeHash: false,
        removeQueryString: false,
    }

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should normalize URLs by replacing IDs in path segments', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/example.html#accounts/ASD123/cards',
                },
            },
        })

        const response = await tester.invoke(commonInputs, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.properties.$current_url).toBe('https://example.com/example.html#accounts/:id/cards')
    })

    it('should remove query parameters from URL hash', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/example.html#accounts/cards?test=foo',
                },
            },
        })

        const response = await tester.invoke(commonInputs, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.properties.$current_url).toBe('https://example.com/example.html#accounts/cards')
    })

    it('should normalize complex URLs with multiple IDs and query parameters', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url:
                        'https://example.com/example.html#/path/to/THE_THING/830baf73-2f70-4194-b18e-8900c0281f49?backUrl=foobar',
                },
            },
        })

        const response = await tester.invoke(commonInputs, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.properties.$current_url).toBe('https://example.com/example.html#/path/to/THE_THING/:id')
    })

    it('should keep domain intact when it contains numbers', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url:
                        'https://example.com/?at=c#/currentAccount/830baf73-2f70-4194-b18e-8900c0281f49/transactions',
                },
            },
        })

        const response = await tester.invoke(commonInputs, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.properties.$current_url).toBe('https://example.com/?at=c#/currentAccount/:id/transactions')
    })

    it('should remove query parameters but keep path in hash', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/index.html?at=c&lang=en#/overview',
                },
            },
        })

        const response = await tester.invoke(
            {
                removeQueryString: true,
                removeHash: false,
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.properties.$current_url).toBe('https://example.com/index.html#/overview')
    })

    it.skip('should normalize encoded URIs', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url:
                        'https%3A%2F%2Fexample.com%2F%3Fat%3Dc%23%2FcurrentAccount%2F830baf73-2f70-4194-b18e-8900c0281f49%2Ftransactions',
                },
            },
        })

        const response = await tester.invoke(commonInputs, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.properties.$current_url).toBe('https://example.com/#/currentAccount/:id/transactions')
    })

    it('should handle multiple URL properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/users/123/profile',
                    $referrer: 'https://google.com/search?q=test',
                    $initial_referrer: 'https://example.com/posts/456',
                    $referring_domain: 'https://example.com/dashboard/789',
                },
            },
        })

        const response = await tester.invoke(commonInputs, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.properties.$current_url).toBe('https://example.com/users/:id/profile')
        expect(result.properties.$referrer).toBe('https://google.com/search?q=test')
        expect(result.properties.$initial_referrer).toBe('https://example.com/posts/:id')
        expect(result.properties.$referring_domain).toBe('https://example.com/dashboard/:id')
    })

    it('should handle $set and $set_once properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $set: {
                        $current_url: 'https://example.com/users/123/profile',
                    },
                    $set_once: {
                        $initial_current_url: 'https://example.com/posts/456',
                    },
                },
            },
        })

        const response = await tester.invoke(commonInputs, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.properties.$set?.$current_url).toBe('https://example.com/users/:id/profile')
        expect(result.properties.$set_once?.$initial_current_url).toBe('https://example.com/posts/:id')
    })

    it('should handle URLs without hash fragments', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/users/123/profile',
                },
            },
        })

        const response = await tester.invoke(commonInputs, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.properties.$current_url).toBe('https://example.com/users/:id/profile')
    })

    it('should handle URLs with only query parameters', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/search?q=test&page=1',
                },
            },
        })

        const response = await tester.invoke(commonInputs, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.properties.$current_url).toBe('https://example.com/search?q=test&page=1')
    })

    it('should handle empty or invalid URLs gracefully', async () => {
        const testCases = [
            { url: '', expected: '' },
            { url: null, expected: null },
            { url: undefined, expected: undefined },
            { url: 'not-a-url', expected: 'not-a-url' },
        ]

        for (const testCase of testCases) {
            mockGlobals = tester.createGlobals({
                event: {
                    properties: {
                        $current_url: testCase.url,
                    },
                },
            })

            const response = await tester.invoke(commonInputs, mockGlobals)

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()

            const result = response.execResult as EventResult
            expect(result.properties.$current_url).toBe(testCase.expected)
        }
    })

    it('should handle URLs with mixed case segments', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/Users/123/Profile/ABC456',
                },
            },
        })

        const response = await tester.invoke(commonInputs, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.properties.$current_url).toBe('https://example.com/Users/:id/Profile/:id')
    })

    it('should preserve segments that are not IDs', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/api/v1/users/123/profile/settings',
                },
            },
        })

        const response = await tester.invoke(commonInputs, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()

        const result = response.execResult as EventResult
        expect(result.properties.$current_url).toBe('https://example.com/api/v1/users/:id/profile/settings')
    })
})
