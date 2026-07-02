import { PLACEHOLDER_SRC, applyBlur, blurInlineImageAttr, isMediaTag } from './assets'
import { BLANK_IMAGE_DATA_URI } from './blur'
import { ImageScrubJob, ScrubContext } from './config'
import { defaultAllowLists } from './default-dict'

// Real PNGs — routing now reads the intrinsic size from the header, so tests use genuine images.
// TINY is 1x1 (below the detector floor => passthrough); BIG is 40x40 (=> scrubbed).
const TINY_PNG =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
const BIG_PNG =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAIAAAADnC86AAAACXBIWXMAAAPoAAAD6AG1e1JrAAAAR0lEQVR4nO3YsQkAIAxEUeu//1A3ljvY2DywD0iSR+6svryjcL56mivjlAUyKzNIhMWwGBaHxbAYFodF12IO80QRE770HDddvGtfTNaUfqIAAAAASUVORK5CYII='
// Not a decodable image — image-size throws, so dimensions are unknown and it must fail closed (scrub).
const GARBAGE_PNG = `data:image/png;base64,${Buffer.from('not-a-real-image-payload').toString('base64')}`

// No-op emit deps: these assets-level tests only exercise routing/collection, so the emit is never run.
const NOOP_PORTS: NonNullable<ScrubContext['imageScrub']> = {
    setBatchContentKeysRedis: () => Promise.resolve([]),
    deleteBatchContentKeysRedis: () => Promise.resolve(),
    produceBatchImagesKafka: () => Promise.resolve(),
}

/** A scrub context with the image-scrub topic ports wired. */
function ctxWithPorts(): {
    ctx: ScrubContext
    imageScrubJobs: ImageScrubJob[]
    blurJobs: NonNullable<ScrubContext['blurJobs']>
} {
    const imageScrubJobs: ImageScrubJob[] = []
    const blurJobs: NonNullable<ScrubContext['blurJobs']> = []
    const ctx: ScrubContext = {
        allow: defaultAllowLists(),
        teamId: 42,
        imageScrub: NOOP_PORTS,
        imageScrubJobs,
        blurJobs,
    }
    return { ctx, imageScrubJobs, blurJobs }
}

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
        const attrs: Record<string, unknown> = { src: BIG_PNG }
        applyBlur(ctx, attrs)
        expect(attrs.src).toBe(PLACEHOLDER_SRC)
        // data-image has no URL to preserve, so no stash is added.
        expect('data-anon-original-src' in attrs).toBe(false)
    })

    describe('inline-image routing', () => {
        it('routes a static <img> inline image to the scrub-topic collector when ports are wired', () => {
            const { ctx, imageScrubJobs, blurJobs } = ctxWithPorts()
            const attrs: Record<string, unknown> = { rr_dataURL: BIG_PNG }

            expect(blurInlineImageAttr(ctx, attrs, 'rr_dataURL', 'img')).toBe(true)
            expect(imageScrubJobs).toHaveLength(1) // collected for the batched emit
            expect(blurJobs).toHaveLength(0) // not blurred in-process
            expect(attrs.rr_dataURL).toBe(BLANK_IMAGE_DATA_URI) // fail-safe until the ref is written

            imageScrubJobs[0].apply('image:42:q1YIODUgcFH6CgV1DOI4SU')
            expect(attrs.rr_dataURL).toBe('image:42:q1YIODUgcFH6CgV1DOI4SU') // reference written in place
        })

        it('blurs a canvas inline image in-process (cheap route), never emitting it', () => {
            const { ctx, imageScrubJobs, blurJobs } = ctxWithPorts()
            const attrs: Record<string, unknown> = { rr_dataURL: BIG_PNG }

            expect(blurInlineImageAttr(ctx, attrs, 'rr_dataURL', 'canvas')).toBe(true)
            expect(blurJobs).toHaveLength(1) // canvas is dynamic → in-process blur
            expect(imageScrubJobs).toHaveLength(0)
            expect(attrs.rr_dataURL).toBe(BLANK_IMAGE_DATA_URI)
        })

        it('passes a tiny inline image through untouched (below the detector floor)', () => {
            const { ctx, imageScrubJobs, blurJobs } = ctxWithPorts()
            const attrs: Record<string, unknown> = { rr_dataURL: TINY_PNG }

            expect(blurInlineImageAttr(ctx, attrs, 'rr_dataURL', 'img')).toBe(false)
            expect(imageScrubJobs).toHaveLength(0)
            expect(blurJobs).toHaveLength(0)
            expect(attrs.rr_dataURL).toBe(TINY_PNG) // untouched
        })

        it('always passes an SVG through untouched, regardless of declared size', () => {
            const { ctx, imageScrubJobs, blurJobs } = ctxWithPorts()
            const svg = `data:image/svg+xml;base64,${Buffer.from(
                '<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="2000"><text>hi</text></svg>'
            ).toString('base64')}`
            const attrs: Record<string, unknown> = { rr_dataURL: svg }

            expect(blurInlineImageAttr(ctx, attrs, 'rr_dataURL', 'img')).toBe(false)
            expect(imageScrubJobs).toHaveLength(0)
            expect(blurJobs).toHaveLength(0)
            expect(attrs.rr_dataURL).toBe(svg) // vector asset, left as-is
        })

        it('scrubs an undecodable image rather than passing it through (fail closed)', () => {
            // The size can't be read, so it must NOT be treated as tiny/passthrough — the raw bytes are
            // handed off to scrubbing, never left inline.
            const { ctx, imageScrubJobs } = ctxWithPorts()
            const attrs: Record<string, unknown> = { rr_dataURL: GARBAGE_PNG }

            expect(blurInlineImageAttr(ctx, attrs, 'rr_dataURL', 'img')).toBe(true)
            expect(imageScrubJobs).toHaveLength(1) // scrubbed (advanced), not passed through
            expect(attrs.rr_dataURL).toBe(BLANK_IMAGE_DATA_URI)
        })

        it('falls back to in-process blur for an <img> when no scrub-topic ports are wired', () => {
            const blurJobs: NonNullable<ScrubContext['blurJobs']> = []
            const noPorts: ScrubContext = { allow: defaultAllowLists(), blurJobs }
            const attrs: Record<string, unknown> = { rr_dataURL: BIG_PNG }

            expect(blurInlineImageAttr(noPorts, attrs, 'rr_dataURL', 'img')).toBe(true)
            expect(blurJobs).toHaveLength(1) // advanced route degrades to blur without ports
            expect(attrs.rr_dataURL).toBe(BLANK_IMAGE_DATA_URI)
        })
    })
})
