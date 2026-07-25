/** Decode the source image ONCE to raw RGB; every stage re-wraps it instead of re-decoding the PNG.
 *  Decoding a multi-megapixel PNG is tens of ms; the pipeline touches the source 4-5 times. */
import sharp from 'sharp'

import { LIMIT_INPUT_PIXELS } from './blur.ts'
import { numFromEnv } from './env.ts'

/**
 * Resolution in this pipeline is one decision, not two.
 *
 * What we store decides what can leak: text below a few pixels in the stored image is unreadable no
 * matter who is looking, so the only text that can leak is text large enough to survive the
 * downscale. What we detect at decides what we catch. Tie them together and the guarantee is
 * structural rather than a pair of constants that happen to be compatible today.
 *
 * Measured floors, both in font-size px (ink is about 0.72x that, see dev/glyph-floor.ts):
 *   ~3px in the stored image is where a person stops reading text
 *   ~9px at the model input is where DBNet reliably finds it
 *
 * So the model has to see every frame at least 3x larger, per axis, than we store it. Anything
 * legible in the artifact is then comfortably above what the detector needs. The same benchmark run
 * for faces and codes (dev/floors.ts) shows both clearing this ratio with margin, so text is what
 * binds.
 */
export const DETECT_OVER_STORE = numFromEnv('SCRUB_DETECT_OVER_STORE', 3, 2, 8)

// Area budget for the STORED image: the permanent record, and the only copy that exists.
export const SCRUB_OUT_MAX_PIXELS = numFromEnv('SCRUB_OUT_MAX_PIXELS', 50_000, 16 * 16, LIMIT_INPUT_PIXELS)

/**
 * Area budget for the frame every detector runs on, derived from the stored size rather than set
 * independently, so the ratio above cannot drift. An explicit SCRUB_MAX_PIXELS still wins, because
 * an operator debugging a recall problem needs to be able to raise it, but it is checked against the
 * ratio at startup rather than trusted.
 *
 * Note this is the frame the models see: DET_FACTOR must stay at 1 for that to hold, or DBNet takes
 * a second downscale on top and the ratio it actually gets is smaller than the one enforced here.
 */
export const SCRUB_MAX_PIXELS = numFromEnv(
    'SCRUB_MAX_PIXELS',
    Math.min(LIMIT_INPUT_PIXELS, SCRUB_OUT_MAX_PIXELS * DETECT_OVER_STORE ** 2),
    96 * 96,
    LIMIT_INPUT_PIXELS
)

/** Throws when the two budgets are set to a pair that lets legible text past the detectors. Called
 *  at startup so a bad pairing never reaches traffic, rather than silently under-redacting. */
export function assertResolutionInvariant(detectPixels: number, storePixels: number, detFactor: number): void {
    const ratio = (Math.sqrt(detectPixels / storePixels) * Math.min(1, detFactor)).toFixed(2)
    if (Number(ratio) < DETECT_OVER_STORE) {
        throw new Error(
            `scrub resolution invariant violated: models would see frames only ${ratio}x the stored size, ` +
                `below the ${DETECT_OVER_STORE}x needed for text legible in the artifact to be detectable ` +
                `(SCRUB_MAX_PIXELS=${detectPixels}, SCRUB_OUT_MAX_PIXELS=${storePixels}, DET_FACTOR=${detFactor})`
        )
    }
}

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
