/** Decode the source image ONCE to raw RGB; every stage re-wraps it instead of re-decoding the PNG.
 *  Decoding a multi-megapixel PNG is tens of ms; the pipeline touches the source 4-5 times. */
import sharp from 'sharp'

import { LIMIT_INPUT_PIXELS } from './blur.ts'

// Every frame is downscaled to this long side inside the decode pipeline, unconditionally. Two
// reasons: (1) memory — compose holds a few full-frame buffers, so the cap bounds the per-image
// working set (~6 MB/frame at 1600 vs ~150 MB at the 50 MP decode limit); (2) fidelity honesty —
// detection runs at <= DET_CAP (1600), so storing pixels above that resolution would preserve
// exactly the detail the detectors never certified as clean.
export const MAX_LONG_SIDE = Number(process.env.SCRUB_MAX_LONG_SIDE ?? 1600)
if (!Number.isFinite(MAX_LONG_SIDE) || MAX_LONG_SIDE < 32) {
    throw new Error(`SCRUB_MAX_LONG_SIDE must be a number >= 32, got ${process.env.SCRUB_MAX_LONG_SIDE}`)
}

export interface Src {
    data: Buffer
    W: number
    H: number
}

export async function decodeSrc(input: Buffer): Promise<Src> {
    const { data, info } = await sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS })
        .resize(MAX_LONG_SIDE, MAX_LONG_SIDE, { fit: 'inside', withoutEnlargement: true })
        .removeAlpha()
        .raw()
        .toBuffer({ resolveWithObject: true })
    return { data, W: info.width, H: info.height }
}

/** A fresh sharp pipeline over the already-decoded raw pixels (no PNG decode). */
export function srcSharp(s: Src): sharp.Sharp {
    return sharp(s.data, { raw: { width: s.W, height: s.H, channels: 3 } })
}
