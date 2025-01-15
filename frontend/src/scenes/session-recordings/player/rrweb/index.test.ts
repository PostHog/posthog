import { CorsPlugin, WindowTitlePlugin } from '.'

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
                            {
                                type: 1,
                                name: 'html',
                            },
                            {
                                type: 2,
                                tagName: 'html',
                                childNodes: [
                                    {
                                        type: 2,
                                        tagName: 'head',
                                        childNodes: [
                                            {
                                                type: 2,
                                                tagName: 'meta',
                                            },
                                            {
                                                type: 2,
                                                tagName: 'title',
                                                attributes: {},
                                                childNodes: [
                                                    {
                                                        id: 123456789,
                                                        type: 3,
                                                        textContent: 'Recordings • PostHog',
                                                    },
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
        // callback for title node
        expect(mockCallback).toHaveBeenCalledWith('0191dd6c-cd35-71ad-9114-264ebef5ab38', 'PostHog • A new title')

        // new full snapshot
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
        // not called because the title references have changed
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
                            {
                                type: 1,
                                name: 'html',
                            },
                            {
                                type: 2,
                                tagName: 'html',
                                childNodes: [
                                    {
                                        type: 2,
                                        tagName: 'head',
                                        childNodes: [
                                            {
                                                type: 2,
                                                tagName: 'meta',
                                            },
                                            {
                                                type: 2,
                                                tagName: 'title',
                                                attributes: {},
                                                childNodes: [
                                                    {
                                                        type: 3,
                                                        textContent: 'Recordings • PostHog',
                                                    },
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
                            {
                                type: 1,
                                name: 'html',
                            },
                            {
                                type: 2,
                                tagName: 'html',
                                childNodes: [
                                    {
                                        type: 2,
                                        tagName: 'head',
                                        childNodes: [
                                            {
                                                type: 2,
                                                tagName: 'meta',
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
})
