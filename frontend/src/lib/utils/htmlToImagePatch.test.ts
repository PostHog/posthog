import { readFileSync } from 'fs'
import { resolveUrl } from 'html-to-image/lib/util'
import { dirname, join } from 'path'

// html-to-image resolves a relative `url()` inside @font-face against the stylesheet's own href.
// Upstream does that by building a detached document, putting a <base href> in it and reading back
// a resolved anchor. Chromium judges that assignment against `base-uri`, so under our policy the
// base is refused, the URL resolves against about:blank and the fetch returns whatever that lands
// on. The library base64s the result and embeds it as a font, so a copied insight image loses its
// typeface with no error anywhere. patches/html-to-image@1.11.13.patch swaps the trick for `new URL`.
//
// The two halves below cover different regressions, because no single assertion covers both.
//
// Resolution is checked by calling the function, so a patch that resolves incorrectly fails here.
// It cannot also catch the patch being dropped: without a CSP header both implementations return
// the same string, which is the point of the change, and jsdom has no CSP. Confirmed by running
// both against the same input under jsdom — identical output.
//
// So the patch being dropped is caught by asserting the <base href> assignment is absent. That is
// the construct the policy rejects. pnpm fails loudly when a patch cannot apply, but not when
// someone removes the entry to unblock an upgrade, which is the path this guards. The check is
// deliberately negative: it says nothing about how the replacement resolves, so an equivalent
// refactor survives.
//
// Both builds this repo loads are guarded, because they are reached differently: esbuild takes
// `module` (es/) and Jest and Node take `main` (lib/). Patching only one of them looks fine locally
// and ships unpatched code to the browser. The package also ships dist/, which only `unpkg` serves,
// so nothing in this repo loads it.
describe('html-to-image patch', () => {
    const packageRoot = dirname(dirname(require.resolve('html-to-image')))
    const STYLESHEET = 'https://app-static-prod.posthog.com/static/index-46THL72U.css'

    // Expectations are written out rather than computed, so the assertion does not restate the
    // implementation it is checking.
    it.each([
        [
            'root-relative, the shape our own index.css ships',
            '/static/assets/Inter-YI3GW4KE.woff2',
            'https://app-static-prod.posthog.com/static/assets/Inter-YI3GW4KE.woff2',
        ],
        ['path-relative', 'Inter.woff2', 'https://app-static-prod.posthog.com/static/Inter.woff2'],
        ['parent segment', '../assets/Inter.woff2', 'https://app-static-prod.posthog.com/assets/Inter.woff2'],
        ['absolute, returned untouched', 'https://cdn.example.com/Inter.woff2', 'https://cdn.example.com/Inter.woff2'],
    ])('resolves a %s font URL against the stylesheet', (_label, url, expected) => {
        expect(resolveUrl(url, STYLESHEET)).toBe(expected)
    })

    it.each(['es/util.js', 'lib/util.js'])('does not assign <base href> on a detached document in %s', (file) => {
        const source = readFileSync(join(packageRoot, file), 'utf-8')

        expect(source).not.toMatch(/createElement\(['"]base['"]\)/)
    })
})
