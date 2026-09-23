import {
    OS_BRIDGE_CHANNEL,
    OS_BRIDGE_VERSION,
    osBridgeSenderWindowId,
    parseOsBridgeMessage,
    parseOsHostMessage,
} from './osBridgeProtocol'
import { osFrameName } from './osFrame'

const ORIGIN = 'https://app.example.com'

function envelope(message: Record<string, unknown>): Record<string, unknown> {
    return { channel: OS_BRIDGE_CHANNEL, version: OS_BRIDGE_VERSION, ...message }
}

describe('osBridgeProtocol', () => {
    test.each([
        [
            'a location report',
            envelope({ type: 'location', path: '/project/1/insights', title: 'Insights', traversed: false }),
            { type: 'location', path: '/project/1/insights', title: 'Insights', traversed: false },
        ],
        [
            'a request for a new window',
            envelope({ type: 'open-window', path: '/project/1/replay' }),
            { type: 'open-window', path: '/project/1/replay' },
        ],
        ['a click into the frame', envelope({ type: 'focus' }), { type: 'focus' }],
        ['a changed user', envelope({ type: 'user-changed' }), { type: 'user-changed' }],
        [
            'a window shortcut',
            envelope({ type: 'window-command', command: 'snap-left' }),
            { type: 'window-command', command: 'snap-left' },
        ],
        [
            'a page that must leave the frame',
            envelope({ type: 'open-top', url: 'https://billing.example.com/checkout' }),
            { type: 'open-top', url: 'https://billing.example.com/checkout' },
        ],
        [
            'a side panel request',
            envelope({ type: 'side-panel', tab: 'max', options: '!why did signups drop' }),
            { type: 'side-panel', tab: 'max', options: '!why did signups drop' },
        ],
        ['a spotlight request', envelope({ type: 'spotlight' }), { type: 'spotlight' }],
        [
            'a location with a long query in the hash',
            envelope({
                type: 'location',
                path: `/project/1/insights/new#q=${'x'.repeat(5000)}`,
                title: '',
                traversed: false,
            }),
            { type: 'location', path: `/project/1/insights/new#q=${'x'.repeat(5000)}`, title: '', traversed: false },
        ],
        ['a message from another channel', { channel: 'other', version: 1, type: 'spotlight' }, null],
        ['a message from a newer protocol', { ...envelope({ type: 'spotlight' }), version: 2 }, null],
        ['an unknown type', envelope({ type: 'eval', code: 'alert(1)' }), null],
        ['a location without a path', envelope({ type: 'location', title: 'x', traversed: false }), null],
        ['an unknown window command', envelope({ type: 'window-command', command: 'delete-everything' }), null],
        ['an open-top with a script url', envelope({ type: 'open-top', url: 'javascript:alert(1)' }), null],
        ['an open-top with a data url', envelope({ type: 'open-top', url: 'data:text/html,hi' }), null],
        ['a string payload', 'focus', null],
        ['null', null, null],
    ])('parses %s', (_description, data, expected) => {
        expect(parseOsBridgeMessage(data)).toEqual(expected)
    })

    test.each([
        ['a changed user', envelope({ type: 'user-changed' }), { type: 'user-changed' }],
        ['a frame-only message', envelope({ type: 'open-window', path: '/project/1/replay' }), null],
        ['a message from another channel', { channel: 'other', version: 1, type: 'user-changed' }, null],
        ['a message from a newer protocol', { ...envelope({ type: 'user-changed' }), version: 2 }, null],
    ])('parses %s from the OS page', (_description, data, expected) => {
        expect(parseOsHostMessage(data)).toEqual(expected)
    })

    describe('sender', () => {
        const insightsFrame = { name: osFrameName('abc123'), contentWindow: {} as Window }
        const replayFrame = { name: osFrameName('def456'), contentWindow: {} as Window }
        const frames = [insightsFrame, replayFrame]

        test.each([
            ['an OS window frame on this origin', ORIGIN, replayFrame.contentWindow, 'def456'],
            ['a page on another origin', 'https://evil.example.com', replayFrame.contentWindow, null],
            ['a window that is not an OS window frame', ORIGIN, {} as Window, null],
            ['a message without a source', ORIGIN, null, null],
        ])('accepts %s', (_description, origin, source, expected) => {
            expect(osBridgeSenderWindowId({ origin, source }, frames, ORIGIN)).toBe(expected)
        })

        it('ignores a frame that is not named as an OS window', () => {
            const unnamed = { name: 'preview', contentWindow: {} as Window }
            expect(osBridgeSenderWindowId({ origin: ORIGIN, source: unnamed.contentWindow }, [unnamed], ORIGIN)).toBe(
                null
            )
        })
    })
})
