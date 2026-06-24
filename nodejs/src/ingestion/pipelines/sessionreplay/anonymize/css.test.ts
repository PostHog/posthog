import { scrubCss } from './css'
import { defaultAllowLists } from './default-dict'

describe('anonymize/css', () => {
    const ctx = { allow: defaultAllowLists(), maxWordsLen: 8 }

    it('redacts PII path segments inside url() targets', () => {
        const result = scrubCss(ctx, '.a { background: url("/users/SecretUser/avatar.png"); }')
        expect(result.changed).toBe(true)
        expect(result.value).not.toContain('SecretUser')
        expect(result.value).toContain('url(')
    })

    it('leaves data-URIs and fragment refs untouched', () => {
        const css = '.a { background: url(data:image/png;base64,AAAA); clip-path: url(#mask); }'
        expect(scrubCss(ctx, css).changed).toBe(false)
    })

    it('returns the input unchanged when there is no url()', () => {
        const css = '.a { color: red; font-weight: bold; }'
        const result = scrubCss(ctx, css)
        expect(result.changed).toBe(false)
        expect(result.value).toBe(css)
    })
})
