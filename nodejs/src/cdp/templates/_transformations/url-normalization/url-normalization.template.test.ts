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

    const invoke = async (inputs: Record<string, any>, globals: HogFunctionInvocationGlobals): Promise<EventResult> => {
        const response = await tester.invoke(inputs, globals)
        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        const result = response.execResult as EventResult
        return result
    }

    it('should normalize URLs by replacing IDs in path segments', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/example.html#accounts/ASD123/cards',
                },
            },
        })

        const result = await invoke(commonInputs, mockGlobals)
        expect(result.properties.$current_url).toBe('https://example.com/example.html#accounts/:id/cards')
    })

    it('should normalize URLs with query parameters', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/example.html?id=120991231290239&test=foo',
                },
            },
        })

        const result = await invoke(commonInputs, mockGlobals)
        expect(result.properties.$current_url).toBe('https://example.com/example.html?id=:id&test=foo')
    })

    it('should normalize URLs with hash parameters', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/example.html#id=120991231290239&test=foo',
                },
            },
        })

        const result = await invoke(commonInputs, mockGlobals)
        expect(result.properties.$current_url).toBe('https://example.com/example.html#id=:id&test=foo')
    })

    it('should remove query parameters from URL hash', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/example.html#accounts/cards?test=foo',
                },
            },
        })

        const result = await invoke(commonInputs, mockGlobals)
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

        const result = await invoke(commonInputs, mockGlobals)
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

        const result = await invoke(commonInputs, mockGlobals)
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

        const result = await invoke(commonInputs, mockGlobals)
        expect(result.properties.$current_url).toBe('https://example.com/#/currentAccount/:id/transactions')
    })

    it('should handle multiple URL properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/users/123/profile',
                    $referrer: 'https://google.com/search?q=test',
                    $referring_domain: 'https://example.com/dashboard/789',
                    not_this_url: 'https://example.com/dashboard/789',
                },
            },
        })

        const response = await tester.invoke(
            {
                removeHash: true,
                removeQueryString: true,
            },
            mockGlobals
        )

        const result = response.execResult as EventResult
        expect(result.properties).toMatchInlineSnapshot(`
            {
              "$current_url": "https://example.com/users/:id/profile",
              "$referrer": "https://google.com/search",
              "$referring_domain": "https://example.com/dashboard/:id",
              "not_this_url": "https://example.com/dashboard/789",
            }
        `)
    })

    it('should handle $set and $set_once properties', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $set: {
                        $current_url: 'https://example.com/users/123/profile',
                    },
                    $set_once: {
                        other_url: 'https://example.com/posts/456',
                        not_this_url: 'https://example.com/posts/456',
                    },
                },
            },
        })

        const response = await tester.invoke(
            {
                urlProperties: '$current_url, other_url',
            },
            mockGlobals
        )

        const result = response.execResult as EventResult
        expect(result.properties).toMatchInlineSnapshot(`
            {
              "$set": {
                "$current_url": "https://example.com/users/:id/profile",
              },
              "$set_once": {
                "not_this_url": "https://example.com/posts/456",
                "other_url": "https://example.com/posts/:id",
              },
            }
        `)
    })

    it('should handle URLs without hash fragments', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/users/123/profile',
                },
            },
        })

        const result = await invoke(commonInputs, mockGlobals)
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

        const result = await invoke(commonInputs, mockGlobals)
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

        const result = await invoke(commonInputs, mockGlobals)
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

        const result = await invoke(commonInputs, mockGlobals)
        expect(result.properties.$current_url).toBe('https://example.com/api/v1/users/:id/profile/settings')
    })
})
