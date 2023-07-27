import { CorsPlugin } from '.'

describe('CorsPlugin', () => {
    it.each([
        `@font-face { font-display: fallback; font-family: "Roboto Condensed"; font-weight: 400; font-style: normal; src: url("https://posthog.com/assets/fonts/roboto/roboto_condensed_reg-webfont.woff2?11012022") format("woff2"), url("https://posthog.com/assets/fonts/roboto/roboto_condensed_reg-webfont.woff?11012022")`,
        `url("https://app.posthog.com/fonts/my-font.woff2")`,
    ])('should replace font urls', (content: string) => {
        expect(CorsPlugin._replaceFontURLs(content)).toMatchSnapshot()
    })
})
