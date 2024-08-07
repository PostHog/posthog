import { CorsPlugin } from '.'

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
