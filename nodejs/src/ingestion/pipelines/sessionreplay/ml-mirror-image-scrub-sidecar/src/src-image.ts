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
 *   ~3px in the STORED image is where a person stops reading text
 *   ~4.9px at the MODEL INPUT is where DBNet starts finding it, ~7px before it finds it every time
 *
 * Text readable in the artifact is at least 3px there, so requiring 7px at the model means the model
 * must see every frame at least 7/3 = 2.33x larger per axis. This enforces 3x, which is deliberate
 * margin: both floors came from one font at near-black on white, and low-contrast or condensed text
 * moves the detection floor up, which is the direction that eats the margin rather than pads it.
 *
 * The same question asked of faces and codes (dev/floors.ts) shows both clearing this with more room
 * than text has, so text is what binds.
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

/**
 * Throws when the two budgets are set to a pair that lets legible text past the detectors. Called at
 * startup so a bad pairing never reaches traffic.
 *
 * This checks the CAPS, which is a configuration sanity check rather than the guarantee: an image
 * under both caps is scaled by neither, so the caps say nothing about it. storedDimsFor derives each
 * image's stored size from what the model actually saw of it, which is what makes the ratio hold per
 * image. Both exist because a bad pairing should fail at startup rather than quietly produce
 * heavily-downscaled output for every image.
 */
/**
 * Stored dimensions for one image, small enough that everything the detectors inspected is at least
 * DETECT_OVER_STORE times larger per axis than what gets kept.
 *
 * Derived per image rather than from the caps, because the caps only bind images above them. An
 * image under both is scaled by neither and would be stored at the same size the model saw it, with
 * no margin at all: text at 4px would be as readable in the artifact as it was invisible to a
 * detector that needs 9px. Small collected sprites are exactly that shape.
 *
 * Takes the model's CONTENT dimensions, not the frame's, so every reduction between the two is
 * already accounted for: the decode cap, the detection budget, DET_FACTOR, and the integer flooring
 * that made a 1920x1080 frame land at 2.99x on one axis while the caps said 3.
 */
export function storedDimsFor(
    frameW: number,
    frameH: number,
    modelW: number,
    modelH: number,
    outMaxPixels: number = SCRUB_OUT_MAX_PIXELS,
    weakestDetectorScale = 1
): { width: number; height: number } {
    // The weakest detector sets the guarantee, not the text detector. YuNet letterboxes the whole
    // frame into a fixed 640 square, so on anything wider than that it sees less of the frame than
    // DBNet does: a 1080p frame reaches DBNet whole and YuNet at 0.72x, which against a stored 0.33x
    // is 2.15x for faces where the text path has 3x. Deriving from DBNet alone published a guarantee
    // that held for one of the three.
    const byDetector = Math.min(modelW / frameW, modelH / frameH, weakestDetectorScale)
    const byInvariant = byDetector / DETECT_OVER_STORE
    const byCap = Math.sqrt(outMaxPixels / (frameW * frameH))
    // Never above 1: a frame smaller than the cap is kept as it is, not stretched up to it.
    const scale = Math.min(1, byInvariant, byCap)
    // Floors, since rounding up by a pixel is what puts the ratio back under the floor.
    return { width: Math.max(1, Math.floor(frameW * scale)), height: Math.max(1, Math.floor(frameH * scale)) }
}

export function assertResolutionInvariant(detectPixels: number, storePixels: number, detFactor: number): void {
    // Compared raw and only formatted for the message: rounding first let 2.996 print as "3.00" and
    // pass a check it fails.
    const ratio = Math.sqrt(detectPixels / storePixels) * Math.min(1, detFactor)
    if (ratio < DETECT_OVER_STORE) {
        throw new Error(
            `scrub resolution invariant violated: models would see frames only ${ratio.toFixed(2)}x the stored size, ` +
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
