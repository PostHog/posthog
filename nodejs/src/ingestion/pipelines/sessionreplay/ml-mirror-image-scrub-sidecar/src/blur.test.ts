import sharp, { type FormatEnum, type Sharp } from 'sharp'

import { UndecodableImageError, blurOnly } from './blur.ts'

describe('blur', () => {
    const swatch = (): Sharp => sharp({ create: { width: 8, height: 8, channels: 3, background: '#0af' } })

    // A capture can name a data URI `image/png` and put any bytes after the comma, and libvips
    // dispatches on magic bytes rather than that name, so the loader set is what actually bounds
    // which decoders user content can reach. TIFF and the HEIF family (AVIF, HEIC) are blocked; the
    // fetcher formats stay reachable.
    //
    // The native VIPS format (`VipsForeignLoadVips`, also blocked in image-input.ts) has no row here: a
    // real `.v`/`.vips` buffer, built with the `vips` CLI, fails to decode with the identical
    // "unsupported image format" error whether or not the block is applied, so there is no buffer
    // that can exercise that branch either way. Blocking it only guards a call path that loads
    // from a file path, which nothing in this sidecar does today.
    it.each(['gif', 'png', 'jpeg', 'webp'])('decodes %s input', async (format) => {
        const bytes = await swatch()
            .toFormat(format as keyof FormatEnum)
            .toBuffer()

        await expect(blurOnly(bytes)).resolves.toBeInstanceOf(Buffer)
    })

    // sharp's prebuilt libvips has no HEVC encoder, so the HEIC case relabels an AVIF file's major
    // (offset 8) and compatible (offset 16 on) ftyp brands as `heic`. The HEIF loader claims a buffer
    // by those brands, so the block has to reject it too.
    const heicBranded = async (): Promise<Buffer> => {
        const bytes = await swatch().avif().toBuffer()
        bytes.write('heic', 8, 'ascii')
        for (let offset = 16; offset + 4 <= bytes.readUInt32BE(0); offset += 4) {
            bytes.write('heic', offset, 'ascii')
        }
        return bytes
    }

    it.each([
        ['TIFF', () => swatch().tiff().toBuffer()],
        ['AVIF', () => swatch().avif().toBuffer()],
        ['HEIC', heicBranded],
    ])('rejects %s input as an unsupported format', async (_format, encode) => {
        const error = await blurOnly(await encode()).catch((e: unknown) => e)

        expect(error).toBeInstanceOf(UndecodableImageError)
        expect(error).toMatchObject({ reason: 'unsupported_format' })
    })
})
