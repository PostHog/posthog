import sharp, { type FormatEnum, type Sharp } from 'sharp'

import { UndecodableImageError, blurOnly } from './blur.ts'

describe('blur', () => {
    const swatch = (): Sharp => sharp({ create: { width: 8, height: 8, channels: 3, background: '#0af' } })

    // A capture can name a data URI `image/png` and put any bytes after the comma, and libvips
    // dispatches on magic bytes rather than that name, so the loader set is what actually bounds
    // which decoders user content can reach. TIFF is blocked in blur.ts; GIF is deliberately not,
    // because pages really do inline GIFs and blocking it would send every one of them to the
    // dead-letter topic.
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
