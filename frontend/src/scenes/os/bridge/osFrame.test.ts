import { isOsFrame, osFrameName, osFrameSrc } from './osFrame'

function fakeWindow(name: string, framed: boolean): Window {
    const win = { name } as { name: string; self?: unknown; top?: unknown }
    win.self = win
    win.top = framed ? {} : win
    return win as unknown as Window
}

describe('osFrame', () => {
    test.each([
        ['an OS window frame', osFrameName('window-1'), true, true],
        ['a frame another site opened, such as posthog.com', '', true, false],
        ['a frame with an unrelated name', 'preview', true, false],
        ['a top-level tab that carries an OS window name', osFrameName('window-1'), false, false],
        ['a plain top-level tab', '', false, false],
    ])('%s', (_description, name, framed, expected) => {
        expect(isOsFrame(fakeWindow(name, framed))).toBe(expected)
    })

    test.each([
        [
            'an app page',
            '/project/1/insights/abc',
            '?dashboard=2',
            '#panel=discussion',
            '/project/1/insights/abc?dashboard=2#panel=discussion',
        ],
        ['a protocol-relative path to another site', '//evil.example.com/login', '', '', null],
        ['a backslash path that browsers read as another site', '/\\evil.example.com/login', '', '', null],
    ])('frame source for %s', (_description, pathname, search, hash, expected) => {
        expect(osFrameSrc({ pathname, search, hash }, 'https://app.example.com')).toBe(expected)
    })
})
