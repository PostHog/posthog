/** Decode the source image ONCE to raw RGB; every stage re-wraps it instead of re-decoding the PNG.
 *  Decoding a multi-megapixel PNG is tens of ms; the pipeline touches the source 4-5 times. */
import sharp from 'sharp'

import { LIMIT_INPUT_PIXELS } from './blur.ts'
import { numFromEnv } from './env.ts'

// Every frame is downscaled (aspect preserved) to this pixel-AREA budget inside the decode,
// unconditionally. Three reasons: (1) memory, because compose holds a few full-frame buffers and
// bytes are proportional to area, so the budget bounds the per-image working set; (2) fidelity
// honesty, because text detection runs under its own area budget, so storing pixels above it would
// preserve exactly the detail the detectors never certified as clean; (3) cost, because decode,
// compose and encode are all linear in area and DBNet's input side scales with sqrt(area), which
// makes this the one dial that reduces most of the pipeline at once.
//
// Lowering it below 1 MP buys less than it looks: adaptiveDetLimit floors at 736, which
// sqrt(1 MP) * DET_FACTOR reaches exactly, so text detection costs the same at any smaller budget
// while the stored frame keeps getting less legible to the model that reads it. An area budget
// rather than a long-side cap so tall pages keep legible native resolution instead of being squashed.
export const SCRUB_MAX_PIXELS = numFromEnv('SCRUB_MAX_PIXELS', 1000 * 1000, 96 * 96, LIMIT_INPUT_PIXELS)

export interface Src {
    data: Buffer
    W: number
    H: number
    /** From the header sharp already read, so reporting the corpus mix costs nothing. */
    format: string
    inputPixels: number
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
    return {
        data,
        W: info.width,
        H: info.height,
        format: meta.format ?? 'unknown',
        inputPixels: meta.width * meta.height,
    }
}

/** A fresh sharp pipeline over the already-decoded raw pixels (no PNG decode). */
export function srcSharp(s: Src): sharp.Sharp {
    return sharp(s.data, { raw: { width: s.W, height: s.H, channels: 3 } })
}
