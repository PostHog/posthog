import { CorsPlugin } from '.'

describe('CorsPlugin', () => {
    it.each([
        `@font-face { font-display: fallback; font-family: "Roboto Condensed"; font-weight: 400; font-style: normal; src: url("https://posthog.com/assets/fonts/roboto/roboto_condensed_reg-webfont.woff2?11012022") format("woff2"), url("https://posthog.com/assets/fonts/roboto/roboto_condensed_reg-webfont.woff?11012022")`,
        `url("https://app.posthog.com/fonts/my-font.woff2")`,
    ])('should replace font urls in stylesheets', (content: string) => {
        expect(CorsPlugin._replaceFontCssUrls(content)).toMatchSnapshot()
    })

    it.each(['https://app.posthog.com/fonts/my-font.woff2?t=1234', 'https://app.posthog.com/fonts/my-font.ttf'])(
        'should replace font urls in links',
        (content: string) => {
            expect(CorsPlugin._replaceFontUrl(content)).toMatchSnapshot()
        }
    )

    it.each(['https://app.posthog.com/my-image.jpeg'])(
        'should not replace non-font urls in links',
        (content: string) => {
            expect(CorsPlugin._replaceFontUrl(content)).toEqual(content)
        }
    )
})
