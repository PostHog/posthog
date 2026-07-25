/** Decode the source image ONCE to raw RGB; every stage re-wraps it instead of re-decoding the PNG.
 *  Decoding a multi-megapixel PNG is tens of ms; the pipeline touches the source 4-5 times. */
import sharp from 'sharp'

import { LIMIT_INPUT_PIXELS } from './blur.ts'
import { numFromEnv } from './env.ts'

// Every frame is downscaled (aspect preserved) to this pixel-AREA budget inside the decode,
// unconditionally. Two reasons: (1) memory, because compose holds a few full-frame buffers and bytes
// are proportional to area, so the budget bounds the per-image working set; (2) fidelity honesty,
// because text detection runs under the same area budget, so storing pixels above it would preserve
// exactly the detail the detectors never certified as clean. An area budget rather than a long-side
// cap so tall pages keep legible native resolution instead of being squashed.
//
// Lowering this is a redaction-recall change, not a cost one: adaptiveDetLimit derives its input
// side from the already-downscaled frame and floors at 736, so any budget at or below 1 MP pins
// detection at that floor and shrinks text relative to it. Re-run `npm run eval` and compare box
// counts, not just leak percentage, before moving it.
export const SCRUB_MAX_PIXELS = numFromEnv('SCRUB_MAX_PIXELS', 1600 * 1600, 96 * 96, LIMIT_INPUT_PIXELS)

// Area budget for the STORED image, applied after detection has run at SCRUB_MAX_PIXELS. Storage
// resolution and detection resolution are separate questions: what a downstream model needs to read
// a session is not what DBNet needs to find 14px text, and tying them together means every pixel
// saved in storage is paid for in recall. Defaults to SCRUB_MAX_PIXELS, which is no downscale at all.
export const SCRUB_OUT_MAX_PIXELS = numFromEnv('SCRUB_OUT_MAX_PIXELS', SCRUB_MAX_PIXELS, 96 * 96, LIMIT_INPUT_PIXELS)

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
