import sharp from 'sharp'

import { blurImageDataUri, isImageDataUri, runBlurJobs } from './blur'

// A small patterned PNG (portable across libvips/libpng builds; a bare 1x1 is rejected by some,
// and a solid color blurs to identical bytes, so we use a checkerboard the blur visibly changes).
const ONE_PX_PNG =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAACXBIWXMAAAPoAAAD6AG1e1JrAAAAJUlEQVQokWN4plEBRyInbOAIlzjDINRAjCJk8cGoYRAG60iMBwA8H08Qor0ygQAAAABJRU5ErkJggg=='

describe('anonymize/blur', () => {
    it('detects image data URIs', () => {
        expect(isImageDataUri('data:image/png;base64,AAAA')).toBe(true)
        expect(isImageDataUri('https://example.com/x.png')).toBe(false)
        expect(isImageDataUri('data:text/plain,hi')).toBe(false)
    })

    it('gaussian-blurs a base64 image into a PNG data URI', async () => {
        const out = await blurImageDataUri(ONE_PX_PNG)
        expect(out).not.toBeNull()
        expect(out!.startsWith('data:image/png;base64,')).toBe(true)
        // It is a real, different encoding, not the original bytes echoed back.
        expect(out).not.toBe(ONE_PX_PNG)
    })

    it('falls back to a downsample when the gaussian blur throws', async () => {
        // Force the Gaussian path to fail; the resize-only fallback should still produce an image.
        const proto = Object.getPrototypeOf(sharp(Buffer.from([0])))
        const spy = jest.spyOn(proto, 'blur').mockImplementation(() => {
            throw new Error('blur boom')
        })
        try {
            const out = await blurImageDataUri(ONE_PX_PNG)
            expect(out).not.toBeNull()
            expect(out!.startsWith('data:image/png;base64,')).toBe(true)
        } finally {
            spy.mockRestore()
        }
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

    it('runBlurJobs runs every job', async () => {
        let ran = 0
        const bump = () => {
            ran++
            return Promise.resolve()
        }
        await runBlurJobs([bump, bump])
        expect(ran).toBe(2)
    })

    it('runBlurJobs swallows a job that throws (already-blanked image is left as-is)', async () => {
        let ran = 0
        await expect(
            runBlurJobs([
                () => Promise.reject(new Error('boom')),
                () => {
                    ran++
                    return Promise.resolve()
                },
            ])
        ).resolves.toBeUndefined()
        expect(ran).toBe(1)
    })
})
