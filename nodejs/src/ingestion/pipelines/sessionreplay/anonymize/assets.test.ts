import { PLACEHOLDER_SRC, applyBlur, isMediaTag } from './assets'
import { defaultAllowLists } from './default-dict'

describe('anonymize/assets', () => {
    const ctx = { allow: defaultAllowLists() }

    it('classifies media tags', () => {
        for (const tag of ['img', 'IMG', 'image', 'video', 'audio', 'source', 'track']) {
            expect(isMediaTag(tag)).toBe(true)
        }
        for (const tag of ['iframe', 'div', 'a']) {
            expect(isMediaTag(tag)).toBe(false)
        }
    })

    it('replaces a remote src with the placeholder and stashes a host+path-scrubbed original', () => {
        const attrs: Record<string, unknown> = { src: 'https://cdn.acme.io/users/42/avatar.png?t=secret' }
        applyBlur(ctx, attrs)
        expect(attrs.src).toBe(PLACEHOLDER_SRC)
        const stash = attrs['data-anon-original-src'] as string
        expect(typeof stash).toBe('string')
        expect(stash).toContain('example.com') // host rewritten
        expect(stash).not.toContain('acme') // original host gone
        expect(stash).not.toContain('42') // path identifier redacted
        expect(stash).not.toContain('secret') // query dropped
    })

    it('replaces a data-image src with the placeholder', () => {
        const attrs: Record<string, unknown> = { src: 'data:image/png;base64,AAAA' }
        applyBlur(ctx, attrs)
        expect(attrs.src).toBe(PLACEHOLDER_SRC)
        // data-image has no URL to preserve, so no stash is added.
        expect('data-anon-original-src' in attrs).toBe(false)
    })
})
