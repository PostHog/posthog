import { blurImageDataUri, isImageDataUri, runBlurJobs } from './blur'

// A 1x1 transparent PNG.
const ONE_PX_PNG =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='

describe('anonymize/blur', () => {
    it('detects image data URIs', () => {
        expect(isImageDataUri('data:image/png;base64,AAAA')).toBe(true)
        expect(isImageDataUri('https://example.com/x.png')).toBe(false)
        expect(isImageDataUri('data:text/plain,hi')).toBe(false)
    })

    it('downscale-blurs a base64 image into a PNG data URI', async () => {
        const out = await blurImageDataUri(ONE_PX_PNG)
        expect(out).not.toBeNull()
        expect(out!.startsWith('data:image/png;base64,')).toBe(true)
        // It is a real, different encoding, not the original bytes echoed back.
        expect(out).not.toBe(ONE_PX_PNG)
    })

    it('returns null for non-image and remote sources', async () => {
        expect(await blurImageDataUri('https://example.com/x.png')).toBeNull()
        expect(await blurImageDataUri('data:text/plain;base64,aGk=')).toBeNull()
        expect(await blurImageDataUri('data:image/png,notbase64')).toBeNull()
        // No comma → not a data URI we can parse.
        expect(await blurImageDataUri('data:image/png')).toBeNull()
    })

    it('runBlurJobs is a no-op for an empty or absent job list', async () => {
        await expect(runBlurJobs([])).resolves.toBeUndefined()
        await expect(runBlurJobs(undefined)).resolves.toBeUndefined()
    })

    it('runBlurJobs replaces the attribute with the blurred result', async () => {
        const attrs: Record<string, unknown> = { src: 'placeholder' }
        await runBlurJobs([{ attrs, key: 'src', dataUri: ONE_PX_PNG }])
        expect(typeof attrs.src).toBe('string')
        expect((attrs.src as string).startsWith('data:image/png;base64,')).toBe(true)
    })

    it('runBlurJobs leaves the attribute untouched when blur fails', async () => {
        const attrs: Record<string, unknown> = { src: 'placeholder' }
        await runBlurJobs([{ attrs, key: 'src', dataUri: 'https://example.com/x.png' }])
        expect(attrs.src).toBe('placeholder')
    })
})
