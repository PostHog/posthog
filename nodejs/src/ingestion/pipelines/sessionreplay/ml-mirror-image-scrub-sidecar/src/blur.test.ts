import { encode as encodeBmp } from 'bmp-ts'
import sharp, { type FormatEnum, type Sharp } from 'sharp'

import { UndecodableImageError, blurOnly } from './blur.ts'

describe('blur', () => {
    const swatch = (): Sharp => sharp({ create: { width: 8, height: 8, channels: 3, background: '#0af' } })
    const bmpSwatch = (): Buffer =>
        encodeBmp({
            width: 8,
            height: 8,
            bitPP: 24,
            data: Buffer.from(Array.from({ length: 8 * 8 }, () => [0, 255, 0, 0]).flat()),
        }).data

    // A capture can name a data URI `image/png` and put any bytes after the comma, and libvips
    // dispatches on magic bytes rather than that name, so the loader set is what actually bounds
    // which decoders user content can reach. TIFF is blocked; the fetcher formats stay reachable.
    //
    // The native VIPS format (`VipsForeignLoadVips`, also blocked in image-input.ts) has no row here: a
    // real `.v`/`.vips` buffer, built with the `vips` CLI, fails to decode with the identical
    // "unsupported image format" error whether or not the block is applied, so there is no buffer
    // that can exercise that branch either way. Blocking it only guards a call path that loads
    // from a file path, which nothing in this sidecar does today.
    it.each(['gif', 'png', 'jpeg', 'webp', 'avif'])('decodes %s input', async (format) => {
        const bytes = await swatch()
            .toFormat(format as keyof FormatEnum)
            .toBuffer()

        await expect(blurOnly(bytes)).resolves.toBeInstanceOf(Buffer)
    })

    it('decodes BMP input through the bounded BMP decoder', async () => {
        const output = await blurOnly(bmpSwatch())
        const pixel = await sharp(output).removeAlpha().raw().toBuffer()

        expect([...pixel]).toEqual([0, 0, 255])
    })

    it('rejects a BMP palette that would allocate beyond the file', async () => {
        const malicious = Buffer.from(bmpSwatch())
        malicious.writeUInt32LE(0xffff_ffff, 46)

        await expect(blurOnly(malicious)).rejects.toBeInstanceOf(UndecodableImageError)
    })

    it.each([1, 2, 0xffff_ffff])('rejects BMP compression mode %s', async (compression) => {
        const compressed = Buffer.from(bmpSwatch())
        compressed.writeUInt32LE(compression, 30)

        await expect(blurOnly(compressed)).rejects.toBeInstanceOf(UndecodableImageError)
    })

    it('rejects TIFF input because it is not an accepted fetcher format', async () => {
        const bytes = await swatch().tiff().toBuffer()

        await expect(blurOnly(bytes)).rejects.toBeInstanceOf(UndecodableImageError)
    })
})
