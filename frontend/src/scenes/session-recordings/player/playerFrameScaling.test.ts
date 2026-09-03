import {
    getPlayerFrameScale,
    isIOS,
    PlayerFrameDimensions,
    PlayerFrameScale,
} from 'scenes/session-recordings/player/playerFrameScaling'

const IPHONE =
    'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1'
const IPAD_LEGACY =
    'Mozilla/5.0 (iPad; CPU OS 12_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.1 Mobile/15E148 Safari/604.1'
// iPadOS 13+ reports the same user agent as desktop Safari. Only maxTouchPoints separates them.
const MAC_SAFARI =
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15'
const MAC_CHROME =
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
const WINDOWS_CHROME =
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
const ANDROID_CHROME =
    'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36'

describe('isIOS', () => {
    const original = { userAgent: navigator.userAgent, maxTouchPoints: navigator.maxTouchPoints }

    function setNavigator(userAgent: string, maxTouchPoints: number): void {
        Object.defineProperty(window.navigator, 'userAgent', { value: userAgent, configurable: true })
        Object.defineProperty(window.navigator, 'maxTouchPoints', { value: maxTouchPoints, configurable: true })
    }

    afterEach(() => {
        setNavigator(original.userAgent, original.maxTouchPoints)
    })

    it.each([
        ['iPhone Safari', IPHONE, 5, true],
        ['iPad on iPadOS 12', IPAD_LEGACY, 5, true],
        ['iPad reporting a Macintosh user agent', MAC_SAFARI, 5, true],
        ['macOS Safari', MAC_SAFARI, 0, false],
        ['macOS Chrome', MAC_CHROME, 0, false],
        ['Windows Chrome', WINDOWS_CHROME, 0, false],
        ['Android Chrome', ANDROID_CHROME, 5, false],
    ] as [string, string, number, boolean][])('%s', (_, userAgent, maxTouchPoints, expected) => {
        setNavigator(userAgent, maxTouchPoints)

        expect(isIOS()).toBe(expected)
    })
})

describe('getPlayerFrameScale', () => {
    it.each([
        [
            'shrinks a desktop capture with transform off iOS',
            { width: 855, height: 500 },
            { width: 1710, height: 881 },
            false,
            { scale: 0.5, zoom: null, transform: 'scale(0.5)' },
        ],
        [
            'shrinks the same capture with zoom on iOS',
            { width: 855, height: 500 },
            { width: 1710, height: 881 },
            true,
            { scale: 0.5, zoom: '0.5', transform: null },
        ],
        [
            'drops the transform when no shrink is needed, so Chrome does not paint outside the clip',
            { width: 1920, height: 1080 },
            { width: 1710, height: 881 },
            false,
            { scale: 1, zoom: null, transform: null },
        ],
        [
            'still sets zoom at full size on iOS',
            { width: 1920, height: 1080 },
            { width: 1710, height: 881 },
            true,
            { scale: 1, zoom: '1', transform: null },
        ],
        [
            'picks the height ratio when that axis is the tighter fit',
            { width: 1710, height: 440 },
            { width: 1710, height: 880 },
            false,
            { scale: 0.5, zoom: null, transform: 'scale(0.5)' },
        ],
    ] as [string, PlayerFrameDimensions, PlayerFrameDimensions, boolean, PlayerFrameScale][])(
        '%s',
        (_, parent, recorded, onIOS, expected) => {
            expect(getPlayerFrameScale(parent, recorded, onIOS)).toEqual(expected)
        }
    )
})
