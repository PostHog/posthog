import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './bot-detection.template'

// TODO we shouldn't need these, our invocation code should use the template defaults correctly
const DEFAULT_INPUTS = {
    userAgent: '$raw_user_agent',
    customBotPatterns: '',
    customIpPrefixes: '',
    filterKnownBotUserAgents: true,
    filterKnownBotIps: true,
    keepUndefinedUseragent: 'Yes',
}

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

        const response = await tester.invoke(DEFAULT_INPUTS, mockGlobals)

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        expect(response.execResult).toBeTruthy()
    })

    it('should filter out known bot user agent', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $raw_user_agent: 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                },
            },
        })

        const response = await tester.invoke(DEFAULT_INPUTS, mockGlobals)

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        expect(response.execResult).toBeFalsy()
    })

    it.each([
        ['Yes', true, undefined],
        ['No', false, undefined],
        ['Yes', true, ''],
        ['No', false, ''],
    ])(
        'should treat missing user agent when keepUndefinedUseragent is %s',
        async (keepUndefinedUseragent, shouldKeepEvent, ua) => {
            mockGlobals = tester.createGlobals({
                event: {
                    properties: {
                        $raw_user_agent: ua,
                    },
                },
            })

            const response = await tester.invoke({ ...DEFAULT_INPUTS, keepUndefinedUseragent }, mockGlobals)

            expect(response.finished).toBeTruthy()
            expect(response.error).toBeFalsy()
            shouldKeepEvent ? expect(response.execResult).toBeTruthy() : expect(response.execResult).toBeFalsy()
        }
    )

    it('should detect bot in case-insensitive manner', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $raw_user_agent: 'Some-CRAWLER-Agent/1.0',
                },
            },
        })

        const response = await tester.invoke(DEFAULT_INPUTS, mockGlobals)

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        expect(response.execResult).toBeFalsy()
    })

    it('should detect custom bot patterns', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $raw_user_agent: 'MyCustomBot/1.0',
                },
            },
        })

        const response = await tester.invoke(
            {
                ...DEFAULT_INPUTS,
                customBotPatterns: 'mycustombot,other-bot',
            },
            mockGlobals
        )

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        expect(response.execResult).toBeFalsy()
    })

    it('should handle empty custom bot patterns', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $raw_user_agent: 'Normal Browser/1.0',
                },
            },
        })

        const response = await tester.invoke(
            {
                ...DEFAULT_INPUTS,
                customBotPatterns: '',
            },
            mockGlobals
        )

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        expect(response.execResult).toBeTruthy()
    })

    it('should block a known bot ip address', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $ip: '5.39.1.225',
                    $raw_user_agent:
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                },
            },
        })

        const response = await tester.invoke(DEFAULT_INPUTS, mockGlobals)

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        expect(response.execResult).toBeFalsy()
    })

    it('should not block a regular ip address', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $ip: '1.2.3.4',
                    $raw_user_agent:
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                },
            },
        })

        const response = await tester.invoke(DEFAULT_INPUTS, mockGlobals)

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        expect(response.execResult).toBeTruthy()
    })

    it('should block a custom IP prefix', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $ip: '1.2.3.4',
                    $raw_user_agent:
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                },
            },
        })

        const response = await tester.invoke(
            {
                ...DEFAULT_INPUTS,
                customIpPrefixes: '1.2.3.0/24',
            },
            mockGlobals
        )

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        expect(response.execResult).toBeFalsy()
    })

    it('should not filter out known bot user agents if filterKnownBotUserAgents is false', async () => {
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
                ...DEFAULT_INPUTS,
                filterKnownBotUserAgents: false,
            },
            mockGlobals
        )

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        expect(response.execResult).toBeTruthy()
    })

    it('should not filter out known bot ips if filterKnownBotIps is false', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $ip: '5.39.1.225',
                    $raw_user_agent:
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                },
            },
        })

        const response = await tester.invoke(
            {
                ...DEFAULT_INPUTS,
                filterKnownBotIps: false,
            },
            mockGlobals
        )

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        expect(response.execResult).toBeTruthy()
    })
})
