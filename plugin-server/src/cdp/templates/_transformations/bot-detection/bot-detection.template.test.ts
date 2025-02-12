import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './bot-detection.template'

describe('bot-detection.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should let normal user agent pass through', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $raw_user_agent:
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                },
            },
        })

        const response = await tester.invoke(
            {
                userAgent: '$raw_user_agent',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toBeDefined()
    })

    it('should filter out known bot user agent', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $raw_user_agent: 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                },
            },
        })

        const response = await tester.invoke(
            {
                userAgent: '$raw_user_agent',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toBeNull()
    })

    it('should handle missing user agent', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {},
            },
        })

        const response = await tester.invoke(
            {
                userAgent: '$raw_user_agent',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toBeDefined()
    })

    it('should detect bot in case-insensitive manner', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $raw_user_agent: 'Some-CRAWLER-Agent/1.0',
                },
            },
        })

        const response = await tester.invoke(
            {
                userAgent: '$raw_user_agent',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toBeNull()
    })

    it('should handle empty user agent string', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $raw_user_agent: '',
                },
            },
        })

        const response = await tester.invoke(
            {
                userAgent: '$raw_user_agent',
            },
            mockGlobals
        )

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toBeDefined()
    })
})
