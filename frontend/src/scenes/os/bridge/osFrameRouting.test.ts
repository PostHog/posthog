import { OsLinkClick, osLinkTarget, osNavigationTarget } from './osFrameRouting'

const ORIGIN = 'https://app.example.com'

function click(href: string, overrides: Partial<OsLinkClick> = {}): OsLinkClick {
    return {
        href,
        target: '',
        download: false,
        button: 0,
        metaKey: false,
        ctrlKey: false,
        shiftKey: false,
        altKey: false,
        ...overrides,
    }
}

describe('osFrameRouting', () => {
    test.each([
        ['a plain in-app click stays in the window', click('/project/1/insights'), null],
        ['a plain click into another app stays in the window', click('/project/1/replay/abc'), null],
        [
            'a Cmd+click opens a new window',
            click('/project/1/insights/abc?x=1#y', { metaKey: true }),
            { kind: 'new-window', path: '/project/1/insights/abc?x=1#y' },
        ],
        [
            'a Ctrl+click opens a new window',
            click(`${ORIGIN}/project/1/insights`, { ctrlKey: true }),
            { kind: 'new-window', path: '/project/1/insights' },
        ],
        [
            'a middle click opens a new window',
            click('/project/1/insights', { button: 1 }),
            { kind: 'new-window', path: '/project/1/insights' },
        ],
        [
            'an in-app link that asks for a new tab opens a new window',
            click('/project/1/insights', { target: '_blank' }),
            { kind: 'new-window', path: '/project/1/insights' },
        ],
        ['a Shift+click keeps the browser behavior', click('/project/1/insights', { shiftKey: true }), null],
        ['an Alt+click keeps the browser download', click('/project/1/insights', { altKey: true }), null],
        ['a download link keeps the browser behavior', click('/project/1/exports/1', { download: true }), null],
        ['a right click does nothing', click('/project/1/insights', { button: 2 }), null],
        [
            'a plain external link opens a browser tab',
            click('https://posthog.com/docs'),
            { kind: 'new-tab', url: 'https://posthog.com/docs' },
        ],
        [
            'a protocol-relative link counts as external',
            click('//evil.example.com/login'),
            { kind: 'new-tab', url: 'https://evil.example.com/login' },
        ],
        [
            'an external link with its own target keeps the browser behavior',
            click('https://x.example.com', { target: '_blank' }),
            null,
        ],
        [
            'a Cmd+click on an external link keeps the browser tab',
            click('https://x.example.com', { metaKey: true }),
            null,
        ],
        ['a plain click on a server page leaves the frame', click('/logout'), { kind: 'top', url: `${ORIGIN}/logout` }],
        ['a server page that asks for a new tab keeps the browser tab', click('/logout', { metaKey: true }), null],
        ['an API link that asks for a new tab keeps the browser tab', click('/api/export', { target: '_blank' }), null],
        ['a mail link keeps the browser behavior', click('mailto:hey@example.com'), null],
        ['a script link does nothing', click('javascript:alert(1)'), null],
        ['a hash link stays in the page', click('#section'), null],
        ['a link with no href does nothing', click(''), null],
    ])('%s', (_description, input, expected) => {
        expect(osLinkTarget(input, `${ORIGIN}/project/1/insights`)).toEqual(expected)
    })

    test.each([
        ['an in-app page load stays in the window', `${ORIGIN}/project/2/insights`, null],
        [
            'an OAuth redirect leaves the frame',
            'https://accounts.example.com/o/oauth2',
            'https://accounts.example.com/o/oauth2',
        ],
        ['a server login page leaves the frame', `${ORIGIN}/login/saml/?idp=x`, `${ORIGIN}/login/saml/?idp=x`],
        [
            'an API redirect leaves the frame',
            `${ORIGIN}/api/integrations/authorize`,
            `${ORIGIN}/api/integrations/authorize`,
        ],
        ['a script url does nothing', 'javascript:alert(1)', null],
    ])('%s', (_description, destination, expected) => {
        expect(osNavigationTarget(destination, ORIGIN)).toBe(expected)
    })
})
