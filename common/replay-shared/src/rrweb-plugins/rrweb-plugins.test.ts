/**
 * @jest-environment jsdom
 */
import { EventType, IncrementalSource, eventWithTime } from 'posthog-js/rrweb-types'

import { BoxOrientPlugin, CorsPlugin, createHLSPlayerPlugin, WindowTitlePlugin } from './index'

describe('CorsPlugin', () => {
    it.each(['https://some-external.js'])('should replace JS urls', (jsUrl) => {
        expect(CorsPlugin._replaceJSUrl(jsUrl)).toEqual(`https://replay.ph-proxy.com/proxy?url=${jsUrl}`)
    })

    it.each([
        `@font-face { font-display: fallback; font-family: "Roboto Condensed"; font-weight: 400; font-style: normal; src: url("https://posthog.com/assets/fonts/roboto/roboto_condensed_reg-webfont.woff2?11012022") format("woff2"), url("https://posthog.com/assets/fonts/roboto/roboto_condensed_reg-webfont.woff?11012022")`,
        `url("https://app.posthog.com/fonts/my-font.woff2")`,
    ])('should replace font urls in stylesheets', (content: string) => {
        expect(CorsPlugin._replaceFontCssUrls(content)).toMatchSnapshot()
    })

    it.each(['https://app.posthog.com/fonts/my-font.woff2?t=1234', 'https://app.posthog.com/fonts/my-font.ttf'])(
        'should replace font urls in links',
        (content: string) => {
            expect(CorsPlugin._replaceFontUrl(content)).toEqual(`https://replay.ph-proxy.com/proxy?url=${content}`)
        }
    )

    it.each([
        'https://app.posthog.com/my-image.jpeg',
        // ttf substring was matching in a previous version
        'https://app-static.eu.posthog.com/static/index-EBVVDttf.css',
    ])('should not replace non-font urls in links', (content: string) => {
        expect(CorsPlugin._replaceFontUrl(content)).toEqual(content)
    })

    it('can replace a modulepreload js link', () => {
        const el = document.createElement('link')
        el.setAttribute('rel', 'modulepreload')
        el.href = 'https://app.posthog.com/my-image.js'
        CorsPlugin.onBuild?.(el, { id: 1, replayer: null as unknown as any })
        expect(el.href).toEqual(`https://replay.ph-proxy.com/proxy?url=https://app.posthog.com/my-image.js`)
    })
})

const mockHlsInstance = {
    loadSource: jest.fn(),
    attachMedia: jest.fn(),
    on: jest.fn(),
    destroy: jest.fn(),
}

const mockHlsClass = Object.assign(
    jest.fn(() => mockHlsInstance),
    {
        isSupported: jest.fn(() => true),
        Events: { ERROR: 'hlsError' },
        ErrorTypes: { NETWORK_ERROR: 'networkError', MEDIA_ERROR: 'mediaError' },
    }
)

jest.mock('hls.js', () => ({ __esModule: true, default: mockHlsClass }))

describe('HLSPlayerPlugin', () => {
    let plugin: ReturnType<typeof createHLSPlayerPlugin>

    // `onBuild` fires `import('hls.js').then(...)` without awaiting it; drain the microtask
    // queue so the handler has run before asserting.
    const delay = (ms = 0): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

    beforeEach(() => {
        jest.clearAllMocks()
        mockHlsClass.isSupported.mockReturnValue(true)
        plugin = createHLSPlayerPlugin()
    })

    it('does nothing for non-video elements', async () => {
        const div = document.createElement('div')
        await plugin.onBuild?.(div, { id: 1, replayer: null as any })
        expect(mockHlsClass).not.toHaveBeenCalled()
    })

    it('does nothing for video elements without hls-src', async () => {
        const video = document.createElement('video')
        await plugin.onBuild?.(video, { id: 1, replayer: null as any })
        expect(mockHlsClass).not.toHaveBeenCalled()
    })

    it('dynamically imports hls.js and attaches to video with hls-src', async () => {
        const video = document.createElement('video')
        video.setAttribute('hls-src', 'https://example.com/stream.m3u8')

        await plugin.onBuild?.(video, { id: 1, replayer: null as any })
        await delay()

        expect(mockHlsClass).toHaveBeenCalled()
        expect(mockHlsInstance.loadSource).toHaveBeenCalledWith('https://example.com/stream.m3u8')
        expect(mockHlsInstance.attachMedia).toHaveBeenCalledWith(video)
        expect(mockHlsInstance.on).toHaveBeenCalledWith('hlsError', expect.any(Function))
    })

    it('falls back to native HLS when Hls.isSupported() is false', async () => {
        mockHlsClass.isSupported.mockReturnValue(false)
        const video = document.createElement('video')
        video.setAttribute('hls-src', 'https://example.com/stream.m3u8')
        video.canPlayType = jest.fn(() => 'maybe') as any

        await plugin.onBuild?.(video, { id: 1, replayer: null as any })
        await delay()

        expect(mockHlsInstance.loadSource).not.toHaveBeenCalled()
        expect(video.src).toContain('https://example.com/stream.m3u8')
    })
})

describe('WindowTitlePlugin', () => {
    it('issues a callback with a valid full snapshot and subsequent incremental mutations', () => {
        const mockCallback = jest.fn()
        const plugin = WindowTitlePlugin(mockCallback)
        plugin.handler?.(
            {
                windowId: '0191dd6c-cd35-71ad-9114-264ebef5ab38',
                type: 2,
                data: {
                    node: {
                        type: 0,
                        childNodes: [
                            { type: 1, name: 'html' },
                            {
                                type: 2,
                                tagName: 'html',
                                childNodes: [
                                    {
                                        type: 2,
                                        tagName: 'head',
                                        childNodes: [
                                            { type: 2, tagName: 'meta' },
                                            {
                                                type: 2,
                                                tagName: 'title',
                                                attributes: {},
                                                childNodes: [
                                                    { id: 123456789, type: 3, textContent: 'Recordings • PostHog' },
                                                ],
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                },
            } as any,
            true,
            { replayer: null as unknown as any }
        )
        expect(mockCallback).toHaveBeenCalledWith('0191dd6c-cd35-71ad-9114-264ebef5ab38', 'Recordings • PostHog')

        mockCallback.mockClear()

        plugin.handler?.(
            {
                type: 3,
                windowId: '0191dd6c-cd35-71ad-9114-264ebef5ab38',
                data: { texts: [{ id: 123, value: 'PostHog • A new title' }] },
            } as any,
            true,
            { replayer: null as unknown as any }
        )
        // not called because the id is not a title element
        expect(mockCallback).not.toHaveBeenCalled()

        plugin.handler?.(
            {
                type: 3,
                windowId: '0191dd6c-cd35-71ad-9114-264ebef5ab38',
                data: { source: 0, texts: [{ id: 123456789, value: 'PostHog • A new title' }] },
            } as any,
            true,
            { replayer: null as unknown as any }
        )
        expect(mockCallback).toHaveBeenCalledWith('0191dd6c-cd35-71ad-9114-264ebef5ab38', 'PostHog • A new title')

        // new full snapshot clears title references
        mockCallback.mockClear()
        plugin.handler?.(
            {
                windowId: '0191dd6c-cd35-71ad-9114-264ebef5ab38',
                type: 2,
                data: { node: { type: 0, childNodes: [] } },
            } as any,
            true,
            { replayer: null as unknown as any }
        )

        plugin.handler?.(
            {
                type: 3,
                windowId: '0191dd6c-cd35-71ad-9114-264ebef5ab38',
                data: { source: 0, texts: [{ id: 123456789, value: 'PostHog • A new title' }] },
            } as any,
            true,
            { replayer: null as unknown as any }
        )
        expect(mockCallback).not.toHaveBeenCalled()
    })

    it('does not issue a callback when the windowId is missing', () => {
        const mockCallback = jest.fn()
        const plugin = WindowTitlePlugin(mockCallback)
        plugin.handler?.(
            {
                type: 2,
                data: {
                    node: {
                        type: 0,
                        childNodes: [
                            { type: 1, name: 'html' },
                            {
                                type: 2,
                                tagName: 'html',
                                childNodes: [
                                    {
                                        type: 2,
                                        tagName: 'head',
                                        childNodes: [
                                            { type: 2, tagName: 'meta' },
                                            {
                                                type: 2,
                                                tagName: 'title',
                                                attributes: {},
                                                childNodes: [{ type: 3, textContent: 'Recordings • PostHog' }],
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                },
            } as any,
            true,
            { replayer: null as unknown as any }
        )
        expect(mockCallback).not.toHaveBeenCalled()
    })

    it('does not issue a callback when no title in head element', () => {
        const mockCallback = jest.fn()
        const plugin = WindowTitlePlugin(mockCallback)
        plugin.handler?.(
            {
                windowId: '0191dd6c-cd35-71ad-9114-264ebef5ab38',
                type: 2,
                data: {
                    node: {
                        type: 0,
                        childNodes: [
                            { type: 1, name: 'html' },
                            {
                                type: 2,
                                tagName: 'html',
                                childNodes: [
                                    {
                                        type: 2,
                                        tagName: 'head',
                                        childNodes: [{ type: 2, tagName: 'meta' }],
                                    },
                                ],
                            },
                        ],
                    },
                },
            } as any,
            true,
            { replayer: null as unknown as any }
        )
        expect(mockCallback).not.toHaveBeenCalled()
    })
})

describe('BoxOrientPlugin', () => {
    const buildContext = { id: 1, replayer: null as unknown as any }

    const styleMutation = (id: number, style: unknown): eventWithTime =>
        ({
            type: EventType.IncrementalSnapshot,
            timestamp: 0,
            data: {
                source: IncrementalSource.Mutation,
                adds: [],
                removes: [],
                texts: [],
                attributes: [{ id, attributes: { style } }],
            },
        }) as unknown as eventWithTime

    const replayerFor = (node: HTMLElement): any => ({ getMirror: () => ({ getNode: () => node }) })

    it('restores the webkit name in a stylesheet Firefox serialized', () => {
        const style = document.createElement('style')
        style.appendChild(
            document.createTextNode(
                '.clamped { display: -webkit-box; -moz-box-orient: vertical; -webkit-line-clamp: 2; }'
            )
        )

        BoxOrientPlugin.onBuild?.(style, buildContext)

        expect(style.textContent).toEqual(
            '.clamped { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }'
        )
    })

    // rrweb builds a stylesheet added after the snapshot as an empty element, then sends its CSS
    // as a separate text node.
    it.each([
        ['style', '.clamped { -moz-box-orient: vertical; }', '.clamped { -webkit-box-orient: vertical; }'],
        ['p', 'the -moz-box-orient rule', 'the -moz-box-orient rule'],
    ])('handles a text node built after its %s parent', (tagName, text, expected) => {
        const parent = document.createElement(tagName)

        BoxOrientPlugin.onBuild?.(parent, buildContext)
        const textNode = document.createTextNode(text)
        parent.appendChild(textNode)
        BoxOrientPlugin.onBuild?.(textNode, buildContext)

        expect(parent.textContent).toEqual(expected)
    })

    it('restores the webkit name in a style attribute', () => {
        const el = document.createElement('p')
        el.setAttribute('style', 'display:-webkit-box;-moz-box-orient:vertical;-webkit-line-clamp:2')

        BoxOrientPlugin.onBuild?.(el, buildContext)

        expect(el.getAttribute('style')).toEqual('display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2')
    })

    it('leaves a node without the moz name alone', () => {
        const el = document.createElement('p')
        el.setAttribute('style', 'color: red')

        BoxOrientPlugin.onBuild?.(el, buildContext)

        expect(el.getAttribute('style')).toEqual('color: red')
    })

    it('restores the webkit name when a mutation replaces the whole style attribute', () => {
        const el = document.createElement('p')
        el.setAttribute('style', 'display:-webkit-box;-moz-box-orient:vertical')

        BoxOrientPlugin.handler?.(styleMutation(7, 'display:-webkit-box;-moz-box-orient:vertical'), false, {
            replayer: replayerFor(el),
        } as any)

        expect(el.getAttribute('style')).toEqual('display:-webkit-box;-webkit-box-orient:vertical')
    })

    it.each([
        ['a plain value', 'vertical', 'vertical', ''],
        ['an important value', ['vertical', 'important'], 'vertical', 'important'],
    ])('sets the webkit property when a mutation carries %s', (_name, mutated, value, priority) => {
        const el = document.createElement('p')
        const setProperty = jest.spyOn(el.style, 'setProperty')

        BoxOrientPlugin.handler?.(styleMutation(7, { '-moz-box-orient': mutated }), false, {
            replayer: replayerFor(el),
        } as any)

        expect(setProperty).toHaveBeenCalledWith('-webkit-box-orient', value, priority)
    })

    it('removes the webkit property when a mutation drops the moz one', () => {
        const el = document.createElement('p')
        const removeProperty = jest.spyOn(el.style, 'removeProperty')

        BoxOrientPlugin.handler?.(styleMutation(7, { '-moz-box-orient': false }), false, {
            replayer: replayerFor(el),
        } as any)

        expect(removeProperty).toHaveBeenCalledWith('-webkit-box-orient')
    })
})
