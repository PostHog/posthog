import { isWebKitBrowser } from './browser'

describe('isWebKitBrowser', () => {
    const cases: [string, NonNullable<Parameters<typeof isWebKitBrowser>[0]>, boolean][] = [
        [
            'Safari on macOS',
            {
                userAgent:
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15',
            },
            true,
        ],
        [
            'Safari on iPhone',
            {
                userAgent:
                    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1',
            },
            true,
        ],
        [
            'Chrome on iOS (CriOS — still WebKit)',
            {
                userAgent:
                    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/126.0.6478.54 Mobile/15E148 Safari/604.1',
            },
            true,
        ],
        [
            'iPadOS in desktop mode (reports as Mac with touch points)',
            {
                userAgent:
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15',
                platform: 'MacIntel',
                maxTouchPoints: 5,
            },
            true,
        ],
        [
            'Chrome on macOS',
            {
                userAgent:
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            },
            false,
        ],
        [
            'Chrome on Windows',
            {
                userAgent:
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            },
            false,
        ],
        [
            'Edge on macOS',
            {
                userAgent:
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0',
            },
            false,
        ],
        [
            'Firefox on macOS',
            {
                userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:127.0) Gecko/20100101 Firefox/127.0',
            },
            false,
        ],
        [
            'Chrome on Android',
            {
                userAgent:
                    'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36',
            },
            false,
        ],
    ]

    it.each(cases)('returns %s -> %s', (_name, nav, expected) => {
        expect(isWebKitBrowser(nav)).toBe(expected)
    })

    it('fails safe (returns false) when no user agent is available', () => {
        expect(isWebKitBrowser(undefined)).toBe(false)
        expect(isWebKitBrowser({ userAgent: '' })).toBe(false)
    })
})
