import { scopeCss, scopeSelector } from './scope-embed-css.mjs'

const ROOT = 'ph-embed'

describe('scopeCss', () => {
    test.each([
        [':root', '.ph-embed'],
        ['html', '.ph-embed'],
        ['body.overflow-hidden', '.ph-embed.overflow-hidden'],
        ['html body .LemonButton', '.ph-embed .LemonButton'],
        ['body > div', '.ph-embed > div'],
        ["[theme='dark']", ".ph-embed[theme='dark']"],
        ["[theme='dark'] .LemonButton", ".ph-embed[theme='dark'] .LemonButton"],
        ['*', '.ph-embed *'],
        ['.LemonButton:hover', '.ph-embed .LemonButton:hover'],
        ['.ph-embed', '.ph-embed'],
        ['.ph-embed .scene', '.ph-embed .scene'],
        ['.ph-embed-floating', '.ph-embed .ph-embed-floating'],
        ['htmlish-widget', '.ph-embed htmlish-widget'],
    ])('scopes %s to %s', (selector, expected) => {
        expect(scopeSelector(selector, ROOT)).toBe(expected)
    })

    it('wraps the stylesheet in one layer and keeps top-level at-rules and keyframe selectors intact', () => {
        const css = [
            '@charset "UTF-8";',
            '@font-face{font-family:Inter;src:url(inter.woff2)}',
            '@layer base{:root{--x:1}}',
            '@keyframes spin{from{opacity:0}to{opacity:1}}',
            '@media (min-width:100px){body,.a{color:red}}',
        ].join('')

        const scoped = scopeCss(css, { rootClass: ROOT, layerName: 'embed' })

        expect(scoped).toBe(
            [
                '@charset "UTF-8";',
                '@font-face{font-family:Inter;src:url(inter.woff2)}',
                '@layer embed{@layer base{.ph-embed{--x:1}}',
                '@keyframes spin{from{opacity:0}to{opacity:1}}',
                '@media (min-width:100px){.ph-embed,.ph-embed .a{color:red}}}',
            ].join('')
        )
    })
})
