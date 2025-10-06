import { PluginEvent } from '@posthog/plugin-scaffold'

import { UserAgentMeta, processEvent } from './index'

function makeMeta(options?: {
    enable?: boolean
    enableSegmentAnalyticsJs?: boolean
    overrideUserAgentDetails?: boolean
    debugMode?: boolean
}): UserAgentMeta {
    return {
        global: {
            enabledPlugin: options?.enable ?? true,
            enableSegmentAnalyticsJs: options?.enableSegmentAnalyticsJs ?? false,
            overrideUserAgentDetails: options?.overrideUserAgentDetails ?? true,
            debugMode: options?.debugMode ?? false,
        },
        config: {
            enable: options?.enable ? 'true' : 'false',
            enableSegmentAnalyticsJs: options?.enableSegmentAnalyticsJs ? 'true' : 'false',
            overrideUserAgentDetails: options?.overrideUserAgentDetails ? 'true' : 'false',
        },
        logger: {
            log: jest.fn(),
            warn: jest.fn(),
        } as any,
    } as unknown as UserAgentMeta
}

describe('useragent-plugin', () => {
    test('should not process event when disabled', () => {
        const event = { properties: {} }
        const processedEvent = processEvent(event as any, makeMeta())
        expect(Object.keys(processedEvent.properties!)).toStrictEqual(Object.keys(event.properties))
    })

    test('should not process event when $userAgent is missing', () => {
        const event = {
            properties: {
                $lib: 'posthog-node',
            },
        } as unknown as PluginEvent

        const processedEvent = processEvent(event, makeMeta())
        expect(Object.keys(processedEvent.properties!)).toStrictEqual(['$lib'])
    })

    test('should not process event when $userAgent is empty', () => {
        const event = {
            properties: {
                $useragent: '',
                $lib: 'posthog-node',
            },
        } as unknown as PluginEvent

        const processedEvent = processEvent(event, makeMeta())
        expect(Object.keys(processedEvent.properties!)).toStrictEqual(['$lib'])
    })

    test('should add user agent details when $useragent property exists', () => {
        const event = {
            properties: {
                $useragent:
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15',
                $lib: 'posthog-node',
            },
        } as unknown as PluginEvent

        const processedEvent = processEvent(event, makeMeta())
        expect(Object.keys(processedEvent.properties!)).toEqual(
            expect.arrayContaining([
                '$lib',
                '$browser',
                '$browser_version',
                '$os',
                '$device',
                '$device_type',
                '$browser_type',
            ])
        )
        expect(processedEvent.properties!).toStrictEqual(
            expect.objectContaining({
                $browser: 'safari',
                $browser_version: '14.0.0',
                $os: 'Mac OS',
            })
        )
    })

    test('should add user agent details when $user-agent property exists', () => {
        const event = {
            properties: {
                '$user-agent':
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15',
                $lib: 'posthog-node',
            },
        } as unknown as PluginEvent

        const processedEvent = processEvent(event, makeMeta())
        expect(Object.keys(processedEvent.properties!)).toEqual(
            expect.arrayContaining([
                '$lib',
                '$browser',
                '$browser_version',
                '$os',
                '$device',
                '$device_type',
                '$browser_type',
            ])
        )
        expect(processedEvent.properties!).toStrictEqual(
            expect.objectContaining({
                $browser: 'safari',
                $browser_version: '14.0.0',
                $os: 'Mac OS',
                $device: '',
                $device_type: 'Desktop',
            })
        )
    })

    test('should add user agent details when $user_agent property exists', () => {
        const event = {
            properties: {
                $user_agent:
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15',
                $lib: 'posthog-node',
            },
        } as unknown as PluginEvent

        const processedEvent = processEvent(event, makeMeta())
        expect(Object.keys(processedEvent.properties!)).toEqual(
            expect.arrayContaining([
                '$lib',
                '$browser',
                '$browser_version',
                '$os',
                '$device',
                '$device_type',
                '$browser_type',
            ])
        )
        expect(processedEvent.properties!).toStrictEqual(
            expect.objectContaining({
                $browser: 'safari',
                $browser_version: '14.0.0',
                $os: 'Mac OS',
                $device: '',
                $device_type: 'Desktop',
            })
        )
    })

    test('should return correct browser properties for given $browser property', () => {
        const event = {
            id: '017dc2cb-9fe0-0000-ceed-5ef8e328261d',
            timestamp: '2021-12-16T10:31:04.234000+00:00',
            event: 'check',
            distinct_id: '91786645996505845983216505144491686624250709556909346823253562854100595129050',
            properties: {
                $ip: '31.164.196.102',
                $lib: 'posthog-python',
                $lib_version: '1.4.4',
                $plugins_deferred: [],
                $plugins_failed: [],
                $plugins_succeeded: ['GeoIP (3347)', 'useragentplugin (3348)'],
                $useragent:
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36 Edg/96.0.1054.57',
            },
            elements_chain: '',
        } as unknown as PluginEvent

        const processedEvent = processEvent(event, makeMeta({ overrideUserAgentDetails: false }))

        expect(Object.keys(processedEvent.properties!)).toEqual(
            expect.arrayContaining(['$browser', '$browser_version', '$os', '$device', '$device_type', '$browser_type'])
        )

        expect(processedEvent.properties!).toStrictEqual(
            expect.objectContaining({
                $browser: 'edge-chromium',
                $browser_version: '96.0.1054',
                $os: 'Mac OS',
                $device: '',
                $device_type: 'Desktop',
            })
        )
    })

    test('should return correct browser properties for an iPhone useragent', () => {
        const event = {
            id: '017dc2cb-9fe0-0000-ceed-5ef8e328261d',
            timestamp: '2021-12-16T10:31:04.234000+00:00',
            event: 'check',
            distinct_id: '91786645996505845983216505144491686624250709556909346823253562854100595129050',
            properties: {
                $ip: '31.164.196.102',
                $lib: 'posthog-python',
                $lib_version: '1.4.4',
                $plugins_deferred: [],
                $plugins_failed: [],
                $plugins_succeeded: ['GeoIP (3347)', 'useragentplugin (3348)'],
                $useragent:
                    'Mozilla/5.0 (iPhone; CPU iPhone OS 15_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Mobile/15E148 Safari/604.1',
            },
            elements_chain: '',
        } as unknown as PluginEvent

        const processedEvent = processEvent(event, makeMeta({ overrideUserAgentDetails: false }))

        expect(Object.keys(processedEvent.properties!)).toEqual(
            expect.arrayContaining(['$browser', '$browser_version', '$os', '$device', '$device_type', '$browser_type'])
        )

        expect(processedEvent.properties!).toStrictEqual(
            expect.objectContaining({
                $browser: 'ios',
                $browser_version: '15.4.0',
                $os: 'iOS',
                $device: 'iPhone',
                $device_type: 'Mobile',
            })
        )
    })

    test('should not override existing properties when overrideUserAgentDetails is disabled', () => {
        const event = {
            properties: {
                $browser: 'safari',
                $browser_version: '14.0',
                $os: 'macos',
                $device: '',
                $device_type: 'Desktop',
                $useragent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:82.0) Gecko/20100101 Firefox/82.0',
                $lib: 'posthog-node',
            },
        } as unknown as PluginEvent

        const processedEvent = processEvent(event, makeMeta({ overrideUserAgentDetails: false }))
        expect(processedEvent.properties!).toStrictEqual(
            expect.objectContaining({
                $browser: 'safari',
                $browser_version: '14.0',
                $os: 'macos',
                $device: '',
                $device_type: 'Desktop',
            })
        )
    })

    describe('enableSegmentAnalyticsJs is true', () => {
        test('should add user agent details when segment_userAgent property exists', () => {
            const event = {
                properties: {
                    segment_userAgent:
                        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15',
                    $lib: 'posthog-node',
                },
            } as unknown as PluginEvent

            const processedEvent = processEvent(event, makeMeta({ enableSegmentAnalyticsJs: true }))
            expect(Object.keys(processedEvent.properties!)).toEqual(
                expect.arrayContaining(['$lib', '$browser', '$browser_version', '$os', '$browser_type'])
            )
            expect(processedEvent.properties!).toStrictEqual(
                expect.objectContaining({
                    $browser: 'safari',
                    $browser_version: '14.0.0',
                    $os: 'Mac OS',
                    segment_userAgent:
                        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15',
                })
            )
        })
    })
})
