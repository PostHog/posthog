import sharp, { type FormatEnum, type Sharp } from 'sharp'

import { UndecodableImageError, blurOnly } from './blur.ts'

describe('blur', () => {
    const swatch = (): Sharp => sharp({ create: { width: 8, height: 8, channels: 3, background: '#0af' } })

    // A capture can name a data URI `image/png` and put any bytes after the comma, and libvips
    // dispatches on magic bytes rather than that name, so the loader set is what actually bounds
    // which decoders user content can reach. TIFF is blocked in blur.ts; GIF is deliberately not,
    // because pages really do inline GIFs and blocking it would send every one of them to the
    // dead-letter topic.
    //
    // The native VIPS format (`VipsForeignLoadVips`, also blocked in blur.ts) has no row here: a
    // real `.v`/`.vips` buffer, built with the `vips` CLI, fails to decode with the identical
    // "unsupported image format" error whether or not the block is applied, so there is no buffer
    // that can exercise that branch either way. Blocking it only guards a call path that loads
    // from a file path, which nothing in this sidecar does today.
    it.each([
        ['tiff', true],
        ['gif', false],
        ['png', false],
        ['jpeg', false],
    ])('%s input is rejected: %s', async (format, blocked) => {
        const bytes = await swatch()
            .toFormat(format as keyof FormatEnum)
            .toBuffer()
        const decode = blurOnly(bytes)
        if (blocked) {
            await expect(decode).rejects.toBeInstanceOf(UndecodableImageError)
        } else {
            await expect(decode).resolves.toBeInstanceOf(Buffer)
        }
    })
})
