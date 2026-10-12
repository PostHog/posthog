import { detectCodexLoginPlatform } from './codexLoginCommands'

describe('detectCodexLoginPlatform', () => {
    it.each([
        ['macOS', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36', 'macos'],
        ['MacIntel', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Version/17.0 Safari/605.1.15', 'macos'],
        ['Windows', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'windows'],
        ['Win32', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0', 'windows'],
        ['Linux x86_64', 'Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0', 'linux'],
        ['Chrome OS', 'Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36', 'linux'],
        ['', '', 'macos'],
    ])('maps platform %j to the right command', (platform, userAgent, expected) => {
        expect(detectCodexLoginPlatform(platform, userAgent)).toBe(expected)
    })
})
