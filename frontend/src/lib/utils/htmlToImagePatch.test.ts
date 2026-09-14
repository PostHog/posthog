import { readFileSync } from 'fs'
import { dirname, join } from 'path'

// html-to-image resolves a relative `url()` inside @font-face by building a detached document,
// putting a <base href> in it and reading back a resolved anchor. Chromium judges that assignment
// against `base-uri`, so under our policy the base is refused, the URL resolves against about:blank
// and the fetch returns whatever that lands on. The library base64s the result and embeds it as a
// font, so a copied insight image loses its typeface with no error anywhere.
//
// patches/html-to-image@1.11.13.patch swaps the trick for `new URL`. pnpm fails loudly when a patch
// cannot apply, but not when someone drops the entry to unblock an upgrade, which is what this
// guards. The behaviour itself needs a real browser and a real CSP header to reproduce, so the
// shipped file is the only thing a unit test can see.
//
// All three builds are checked because the package ships three and they are reached differently:
// esbuild takes `module` (es/), Jest and Node take `main` (lib/), and `unpkg` serves dist/. Patching
// only one of them looks fine locally and ships unpatched code.
describe('html-to-image patch', () => {
    const packageRoot = dirname(dirname(require.resolve('html-to-image')))

    it.each(['es/util.js', 'lib/util.js', 'dist/html-to-image.js'])(
        'resolves URLs with the URL constructor in %s',
        (file) => {
            const source = readFileSync(join(packageRoot, file), 'utf-8')

            expect(source).toContain('new URL(')
            expect(source).not.toMatch(/createElement\(['"]base['"]\)/)
        }
    )
})
