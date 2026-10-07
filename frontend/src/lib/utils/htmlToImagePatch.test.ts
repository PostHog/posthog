import { readFileSync } from 'fs'
import { getFontEmbedCSS, toBlob } from 'html-to-image'
import { cloneNode } from 'html-to-image/lib/clone-node'
import { resourceToDataURL } from 'html-to-image/lib/dataurl'
import * as imageUtils from 'html-to-image/lib/util'
import { dirname, join } from 'path'

import { BLANK_IMAGE } from './captureElementImage'

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
    afterEach(() => {
        jest.restoreAllMocks()
        document.body.innerHTML = ''
    })

    const STYLESHEET = 'https://app-static-prod.posthog.com/static/index-46THL72U.css'

    function imageBlob(content: string): Blob {
        const iframe = document.createElement('iframe')
        document.body.appendChild(iframe)
        const { Blob: RealmBlob } = iframe.contentWindow as Window & typeof globalThis
        return new RealmBlob([content], { type: 'image/png' })
    }

    function response(status: number, content = '<html>'): Response {
        return { ok: status < 400, status, headers: new Headers(), blob: async () => imageBlob(content) } as Response
    }

    function stubImageLoading(decode: () => Promise<void>): void {
        jest.spyOn(window, 'Image').mockImplementation(() => {
            const img = document.createElement('img')
            img.decode = decode
            Object.defineProperty(img, 'src', {
                set: () => setTimeout(() => img.dispatchEvent(new Event('load'))),
            })
            return img
        })
    }

    it.each([
        [
            'video with an undecodable poster',
            (createImage: jest.SpyInstance): HTMLElement => {
                createImage.mockRejectedValueOnce(new Event('error'))
                const video = document.createElement('video')
                video.poster = 'data:image/png;base64,aW52YWxpZA=='
                return video
            },
        ],
        [
            'video with an unreadable frame',
            (): HTMLElement => {
                const video = document.createElement('video')
                Object.defineProperty(video, 'currentSrc', { value: 'https://example.com/video.mp4' })
                jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
                jest.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockImplementation(() => {
                    throw new DOMException('Canvas is tainted', 'SecurityError')
                })
                return video
            },
        ],
    ])('keeps the box of a %s', async (_label, buildElement) => {
        const image = document.createElement('img')
        const createImage = jest.spyOn(imageUtils, 'createImage').mockResolvedValue(image)
        jest.spyOn(console, 'error').mockImplementation(() => {})
        const element = buildElement(createImage)
        element.style.cssText = 'width: 240px; height: 120px; display: block'

        const clone = await cloneNode(element, {
            imagePlaceholder: BLANK_IMAGE,
            includeStyleProperties: ['width', 'height', 'display'],
        })

        expect(clone).toBe(image)
        expect(image.style.width).toBe('240px')
        expect(image.style.height).toBe('120px')
        expect(image.style.display).toBe('block')
        expect(createImage).toHaveBeenLastCalledWith(BLANK_IMAGE)
    })

    it('replaces a tainted canvas with a blank image of the same size', async () => {
        jest.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockImplementation(function (this: HTMLCanvasElement) {
            return `data:image/png;blank-${this.width}x${this.height}`
        })
        const canvas = document.createElement('canvas')
        canvas.width = 240
        canvas.height = 120
        Object.defineProperty(canvas, 'toDataURL', {
            value: () => {
                throw new DOMException('Canvas is tainted', 'SecurityError')
            },
        })
        const image = document.createElement('img')
        const createImage = jest.spyOn(imageUtils, 'createImage').mockResolvedValue(image)

        await expect(cloneNode(canvas, {})).resolves.toBe(image)
        expect(createImage).toHaveBeenCalledWith('data:image/png;blank-240x120')
    })

    it.each([
        ['import', (href: string): CSSRule[] => [{ type: CSSRule.IMPORT_RULE, href } as CSSImportRule]],
        [
            'cross-origin',
            (): CSSRule[] => {
                throw new DOMException('Cross-origin stylesheet', 'SecurityError')
            },
        ],
    ])('settles an aborted %s stylesheet fetch', async (kind, readRules) => {
        const controller = new AbortController()
        const node = document.createElement('div')
        const sheet = {
            href: `https://example.com/${kind}.css`,
            get cssRules(): CSSRule[] {
                return readRules(this.href)
            },
        }
        Object.defineProperty(node, 'ownerDocument', { value: { styleSheets: [sheet] } })
        jest.spyOn(console, 'error').mockImplementation(() => {})
        jest.spyOn(global, 'fetch').mockImplementation(
            (_url, init) =>
                new Promise((_resolve, reject) => {
                    init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true })
                })
        )

        const result = getFontEmbedCSS(node, { fetchRequestInit: { signal: controller.signal } })
        controller.abort()

        await expect(result).resolves.toBe('')
    })

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
        expect(imageUtils.resolveUrl(url, STYLESHEET)).toBe(expected)
    })

    it.each(['es/util.js', 'lib/util.js'])('does not assign <base href> on a detached document in %s', (file) => {
        const source = readFileSync(join(packageRoot, file), 'utf-8')

        expect(source).not.toMatch(/createElement\(['"]base['"]\)/)
    })

    it.each([
        [
            'a rejected fetch',
            'rejected',
            (): Promise<Response> => Promise.reject(new DOMException('Unavailable', 'AbortError')),
        ],
        ['a 403 error page', 'forbidden', async (): Promise<Response> => response(403)],
        ['a 500 error page', 'server-error', async (): Promise<Response> => response(500)],
    ])(
        'uses the placeholder for %s and retries the image without caching the placeholder',
        async (_label, name, failure) => {
            const url = `https://example.com/${name}.png`
            const fetch = jest
                .spyOn(global, 'fetch')
                .mockImplementationOnce(failure)
                .mockResolvedValue(response(200, 'recovered'))
            jest.spyOn(console, 'warn').mockImplementation(() => {})

            const load = (): Promise<string> => resourceToDataURL(url, 'image/png', { imagePlaceholder: BLANK_IMAGE })

            expect(await load()).toBe(BLANK_IMAGE)
            expect(await load()).toBe('data:image/png;base64,cmVjb3ZlcmVk')
            expect(await load()).toBe('data:image/png;base64,cmVjb3ZlcmVk')
            expect(fetch).toHaveBeenCalledTimes(2)
        }
    )

    it('embeds a font from an unreadable stylesheet without writing into the page stylesheets', async () => {
        const pageStyle = document.createElement('style')
        pageStyle.textContent = 'body { margin: 0 }'
        document.head.appendChild(pageStyle)
        const pageSheet = pageStyle.sheet as CSSStyleSheet
        const crossOriginSheet = {
            href: 'https://fonts.example.com/unreadable.css',
            get cssRules(): CSSRule[] {
                throw new DOMException('Cross-origin stylesheet', 'SecurityError')
            },
        }
        const node = document.createElement('div')
        node.innerHTML = '<span style="font-family: Fancy">x</span>'
        Object.defineProperty(node, 'ownerDocument', { value: { styleSheets: [pageSheet, crossOriginSheet] } })
        jest.spyOn(console, 'error').mockImplementation(() => {})
        jest.spyOn(global, 'fetch').mockImplementation(async (url) =>
            String(url).endsWith('.css')
                ? ({
                      ok: true,
                      status: 200,
                      text: async () => '@font-face { font-family: Fancy; src: url(fancy.woff2) format("woff2") }',
                  } as Response)
                : response(200, 'font')
        )

        const css = await getFontEmbedCSS(node, {})

        expect(css).toContain('font-family: Fancy')
        expect(css).toContain('Zm9udA==')
        expect(pageSheet.cssRules).toHaveLength(1)
        pageStyle.remove()
    })

    it('finds the fonts of an element that lives in another document', async () => {
        const iframe = document.createElement('iframe')
        document.body.appendChild(iframe)
        const doc = iframe.contentDocument as Document
        const style = doc.createElement('style')
        style.textContent = '@font-face { font-family: Fancy; src: url(data:font/woff2;base64,AAAA) format("woff2") }'
        doc.head.appendChild(style)
        const root = doc.createElement('div')
        root.innerHTML = '<header><span style="font-family: Fancy">Heading</span></header>'
        doc.body.appendChild(root)

        await expect(getFontEmbedCSS(root, {})).resolves.toContain('font-family: Fancy')
    })

    it('settles createImage when decode() rejects after the image loaded', async () => {
        stubImageLoading(() => Promise.reject(new DOMException('Decode failed', 'EncodingError')))

        await expect(imageUtils.createImage('https://example.com/huge.svg')).resolves.toMatchObject({ tagName: 'IMG' })
    })

    it('encodes the blob in the requested type and quality', async () => {
        Object.defineProperty(window, 'SVGImageElement', { value: class {}, configurable: true })
        try {
            jest.spyOn(imageUtils, 'createImage').mockResolvedValue(document.createElement('img'))
            jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
                drawImage: () => {},
                fillRect: () => {},
            } as never)
            const encode = jest
                .spyOn(HTMLCanvasElement.prototype, 'toBlob')
                .mockImplementation((callback, type) => callback(new Blob([], { type })))

            const blob = await toBlob(document.createElement('div'), {
                type: 'image/jpeg',
                quality: 0.7,
                width: 10,
                height: 10,
                skipFonts: true,
            })

            expect(blob?.type).toBe('image/jpeg')
            expect(encode).toHaveBeenCalledWith(expect.any(Function), 'image/jpeg', 0.7)
        } finally {
            delete (window as Partial<typeof window>).SVGImageElement
        }
    })
})
