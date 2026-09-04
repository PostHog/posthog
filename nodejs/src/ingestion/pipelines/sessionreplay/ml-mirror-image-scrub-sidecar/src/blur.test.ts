import sharp, { type FormatEnum, type Sharp } from 'sharp'

import { UndecodableImageError, blurOnly } from './blur.ts'

describe('blur', () => {
    const swatch = (): Sharp => sharp({ create: { width: 8, height: 8, channels: 3, background: '#0af' } })

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

    it('rejects TIFF input because it is not an accepted fetcher format', async () => {
        const bytes = await swatch().tiff().toBuffer()

        await expect(blurOnly(bytes)).rejects.toBeInstanceOf(UndecodableImageError)
    })
})
