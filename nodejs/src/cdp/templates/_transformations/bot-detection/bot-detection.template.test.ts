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
            if (shouldKeepEvent) {
                expect(response.execResult).toBeTruthy()
            } else {
                expect(response.execResult).toBeFalsy()
            }
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

    it.each([
        [
            'drops a randomized 4-digit Chrome patch on an Android template',
            'Mozilla/5.0 (Linux; Android 8.0; Pixel 2 Build/OPD3.170816.012) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/47.0.3184.1529 Mobile Safari/537.36',
            true,
            false,
        ],
        [
            'drops a randomized 4-digit Chrome patch on a desktop template',
            'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.7306.1647 Safari/537.36',
            true,
            false,
        ],
        [
            'keeps the impossible Chrome patch when filterKnownBotUserAgents is false',
            'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.7306.1647 Safari/537.36',
            false,
            true,
        ],
        [
            'keeps Yandex Browser, which puts its own build in the patch slot',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.1994 YaBrowser/24.4.1.994 Yowser/2.5 Safari/537.36',
            true,
            true,
        ],
        [
            'keeps Yandex Search App, which puts its own build in the patch slot',
            'Mozilla/5.0 (Linux; arm_64; Android 13; SM-A536B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.6723.2214 YaApp_Android/25.10.1 YaSearchBrowser/25.10.1 BroPP/1.0 Mobile Safari/537.36',
            true,
            true,
        ],
        [
            'keeps Chrome 4, which really shipped a 4-digit patch',
            'Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US) AppleWebKit/532.5 (KHTML, like Gecko) Chrome/4.1.249.1025 Safari/532.5',
            true,
            true,
        ],
        [
            'keeps Opera Mobile with a 4-digit Chrome patch',
            'Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.8812 Mobile Safari/537.36 OPR/62.1.3134.58322',
            true,
            true,
        ],
        [
            'keeps a regular Chrome version',
            'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.7339.207 Mobile Safari/537.36',
            true,
            true,
        ],
    ])('impossible Chrome patch version: %s', async (_name, ua, filterKnownBotUserAgents, shouldKeepEvent) => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $lib: 'web',
                    $raw_user_agent: ua,
                },
            },
        })

        const response = await tester.invoke({ ...DEFAULT_INPUTS, filterKnownBotUserAgents }, mockGlobals)

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        if (shouldKeepEvent) {
            expect(response.execResult).toBeTruthy()
        } else {
            expect(response.execResult).toBeFalsy()
        }
    })

    it.each([
        ['posthog-python', 'python-httpx'],
        ['posthog-node', 'axios/1.4.0'],
        ['posthog-webhook', 'okhttp/4.10.0'],
        ['posthog-ios', 'CFNetwork/1410.0.3'],
    ])('should skip PostHog-curated bot UA list when $lib=%s (non-browser SDK)', async (lib, ua) => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $lib: lib,
                    $raw_user_agent: ua,
                },
            },
        })

        const response = await tester.invoke(DEFAULT_INPUTS, mockGlobals)

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        expect(response.execResult).toBeTruthy()
    })

    it('should skip PostHog-curated bot IP list when $lib is a non-browser SDK', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $lib: 'posthog-python',
                    $ip: '5.39.1.225',
                    $raw_user_agent: 'python-httpx',
                },
            },
        })

        const response = await tester.invoke(DEFAULT_INPUTS, mockGlobals)

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        expect(response.execResult).toBeTruthy()
    })

    it('should still apply customBotPatterns even for non-browser $lib', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $lib: 'posthog-python',
                    $raw_user_agent: 'MyCustomBot/1.0',
                },
            },
        })

        const response = await tester.invoke(
            {
                ...DEFAULT_INPUTS,
                customBotPatterns: 'mycustombot',
            },
            mockGlobals
        )

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        expect(response.execResult).toBeFalsy()
    })

    it('should still apply customIpPrefixes even for non-browser $lib', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $lib: 'posthog-python',
                    $ip: '1.2.3.4',
                    $raw_user_agent: 'python-httpx',
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

    it.each([
        ['web', 'web' as string | undefined],
        ['js', 'js' as string | undefined],
        ['(missing)', undefined as string | undefined],
    ])('should still filter known bot UA when $lib=%s (browser or unknown source)', async (_label, lib) => {
        const properties: Record<string, string> = {
            $raw_user_agent: 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
        }
        if (lib !== undefined) {
            properties.$lib = lib
        }
        mockGlobals = tester.createGlobals({ event: { properties } })

        const response = await tester.invoke(DEFAULT_INPUTS, mockGlobals)

        expect(response.finished).toBeTruthy()
        expect(response.error).toBeFalsy()
        expect(response.execResult).toBeFalsy()
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
