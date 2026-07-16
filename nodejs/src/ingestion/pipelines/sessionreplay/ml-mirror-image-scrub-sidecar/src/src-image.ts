/** Decode the source image ONCE to raw RGB; every stage re-wraps it instead of re-decoding the PNG.
 *  Decoding a multi-megapixel PNG is tens of ms; the pipeline touches the source 4-5 times. */
import sharp from 'sharp'

import { LIMIT_INPUT_PIXELS } from './blur.ts'
import { numFromEnv } from './env.ts'

// Every frame is downscaled (aspect preserved) to this pixel-AREA budget inside the decode,
// unconditionally. Two reasons: (1) memory — compose holds a few full-frame buffers, and bytes are
// proportional to area, so the budget bounds the per-image working set (~8 MB/frame at 1600^2 vs
// ~150 MB at the 50 MP decode limit); (2) fidelity honesty — text detection runs under the same
// area budget (DET_CAP^2), so storing pixels above it would preserve exactly the detail the
// detectors never certified as clean. An area budget rather than a long-side cap so tall pages
// (skyscraper screenshots, infographics) keep legible native resolution instead of being squashed.
export const SCRUB_MAX_PIXELS = numFromEnv('SCRUB_MAX_PIXELS', 1600 * 1600, 96 * 96, LIMIT_INPUT_PIXELS)

export interface Src {
    data: Buffer
    W: number
    H: number
}

export async function decodeSrc(input: Buffer): Promise<Src> {
    const meta = await sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS }).metadata()
    if (!meta.width || !meta.height) {
        throw new Error('image has invalid dimensions')
    }
    const scale = Math.min(1, Math.sqrt(SCRUB_MAX_PIXELS / (meta.width * meta.height)))
    const targetW = Math.max(1, Math.round(meta.width * scale))
    const targetH = Math.max(1, Math.round(meta.height * scale))
    // flatten, NOT removeAlpha: removeAlpha discards the alpha channel but keeps the RGB underneath,
    // so content hidden under fully transparent pixels (invisible in the replay) would surface in
    // the scrubbed output. Flatten composites over a background, destroying hidden RGB.
    const { data, info } = await sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS })
        .resize(targetW, targetH, { fit: 'fill' })
        .flatten({ background: '#fff' })
        .raw()
        .toBuffer({ resolveWithObject: true })
    return { data, W: info.width, H: info.height }
}

/** A fresh sharp pipeline over the already-decoded raw pixels (no PNG decode). */
export function srcSharp(s: Src): sharp.Sharp {
    return sharp(s.data, { raw: { width: s.W, height: s.H, channels: 3 } })
}
