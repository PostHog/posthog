import { generateColorSystemCSS } from './colors'

describe('generateColorSystemCSS', () => {
    test('puts a type-qualified dark selector before the scope so the selector stays valid', () => {
        const css = generateColorSystemCSS(undefined, { scope: '[data-quill]', darkSelector: ['html.dark'] })

        expect(css).toContain('html.dark[data-quill],')
        expect(css).toContain('html.dark[data-quill] *')
        expect(css).toContain('html.dark[data-quill-inverted]')
        expect(css).not.toContain('[data-quill]html.dark')
        expect(css).not.toContain('[data-quill-inverted]html.dark')
    })
})
