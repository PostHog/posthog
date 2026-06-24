import { PLACEHOLDER_SRC, applyBlur, isMediaTag } from './assets'
import { defaultAllowLists } from './default-dict'

describe('anonymize/assets', () => {
    const ctx = { allow: defaultAllowLists(), maxWordsLen: 8 }

    it('classifies media tags', () => {
        for (const tag of ['img', 'IMG', 'image', 'video', 'audio', 'source', 'track']) {
            expect(isMediaTag(tag)).toBe(true)
        }
        for (const tag of ['iframe', 'div', 'a']) {
            expect(isMediaTag(tag)).toBe(false)
        }
    })

    it('replaces a remote src with the placeholder and preserves the URL', () => {
        const attrs: Record<string, unknown> = { src: 'https://example.com/u/abc.png' }
        applyBlur(ctx, attrs)
        expect(attrs.src).toBe(PLACEHOLDER_SRC)
        expect('data-original-src' in attrs).toBe(true)
    })

    it('replaces a data-image src with the placeholder', () => {
        const attrs: Record<string, unknown> = { src: 'data:image/png;base64,AAAA' }
        applyBlur(ctx, attrs)
        expect(attrs.src).toBe(PLACEHOLDER_SRC)
        // data-image has no URL to preserve, so no data-original-* is added.
        expect('data-original-src' in attrs).toBe(false)
    })
})
