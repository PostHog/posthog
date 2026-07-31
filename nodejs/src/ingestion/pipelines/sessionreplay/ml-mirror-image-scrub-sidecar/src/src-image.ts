/** Decode the source image ONCE to raw RGB; every stage re-wraps it instead of re-decoding the PNG.
 *  Decoding a multi-megapixel PNG is tens of ms; the pipeline touches the source 4-5 times. */
import sharp, { type Sharp } from 'sharp'

import { LIMIT_INPUT_PIXELS } from './blur.ts'
import { type Dims, limitsFromEnv, planScales } from './scale-plan.ts'

export interface Src {
    data: Buffer
    W: number
    H: number
    /** From the header sharp already read, so reporting the corpus mix costs nothing. */
    format: string
    inputPixels: number
}

/** Source dimensions from the header alone, so the plan can be made before any pixel is decoded. */
export async function probeDims(input: Buffer): Promise<Dims> {
    const meta = await sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS }).metadata()
    if (!meta.width || !meta.height) {
        throw new Error('image has invalid dimensions')
    }
    return { width: meta.width, height: meta.height }
}

/**
 * Decode to the frame the plan asked for.
 *
 * The target comes in rather than being computed here: every stage's size is one decision made in
 * scale-plan.ts before any pixel is read, so a reader never has to reconstruct the geometry from the
 * modules that happen to apply it.
 */
export async function decodeSrc(input: Buffer, frame?: Dims): Promise<Src> {
    const meta = await sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS }).metadata()
    if (!meta.width || !meta.height) {
        throw new Error('image has invalid dimensions')
    }
    const target = frame ?? planScales({ width: meta.width, height: meta.height }, limitsFromEnv()).frame
    const targetW = target.width
    const targetH = target.height
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
export function srcSharp(s: Src): Sharp {
    return sharp(s.data, { raw: { width: s.W, height: s.H, channels: 3 } })
}
