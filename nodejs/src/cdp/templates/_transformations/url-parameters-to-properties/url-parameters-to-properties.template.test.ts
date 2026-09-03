import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './url-parameters-to-properties.template'

describe('url-parameters-to-properties.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const invoke = async (inputs: Record<string, any>, globals: HogFunctionInvocationGlobals): Promise<any> => {
        const response = await tester.invoke(inputs, globals)
        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        return response.execResult as any
    }

    it('copies named parameters into event properties and decodes values', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $current_url: 'https://example.com/?utm_source=google&utm_campaign=spring%20sale&ignore=me',
                },
            },
        })

        const result = await invoke({ parameters: 'utm_source, utm_campaign' }, mockGlobals)

        expect(result.properties.utm_source).toBe('google')
        expect(result.properties.utm_campaign).toBe('spring sale')
        expect(result.properties.ignore).toBeUndefined()
    })

    it('applies prefix and suffix and writes $set and $set_once', async () => {
        mockGlobals = tester.createGlobals({
            event: { properties: { $current_url: 'https://example.com/?ref=abc' } },
        })

        const result = await invoke(
            {
                parameters: 'ref',
                prefix: 'utm_',
                suffix: '_param',
                setAsUserProperties: true,
                setAsInitialUserProperties: true,
            },
            mockGlobals
        )

        expect(result.properties.utm_ref_param).toBe('abc')
        expect(result.properties.$set.utm_ref_param).toBe('abc')
        expect(result.properties.$set_once.initial_utm_ref_param).toBe('abc')
    })

    it('stores repeated parameters as a JSON array', async () => {
        mockGlobals = tester.createGlobals({
            event: { properties: { $current_url: 'https://example.com/?tag=a&tag=b' } },
        })

        const result = await invoke({ parameters: 'tag' }, mockGlobals)

        expect(result.properties.tag).toBe('["a","b"]')
    })

    it('leaves the event unchanged when the URL has no query string', async () => {
        mockGlobals = tester.createGlobals({
            event: { properties: { $current_url: 'https://example.com/home' } },
        })

        const result = await invoke({ parameters: 'utm_source' }, mockGlobals)

        expect(result.properties).toEqual({ $current_url: 'https://example.com/home' })
    })
})
