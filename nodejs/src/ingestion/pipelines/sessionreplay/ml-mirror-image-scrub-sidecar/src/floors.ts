/**
 * What each detector can find, against what a person can still take out of the stored image.
 *
 * These two numbers are the whole basis of the scrub's sizing. Everything downstream is arithmetic
 * on them: the detectors have to see each subject large enough to find it, and the stored image has
 * to be small enough that anything they missed carries nothing. The gap between the pair is the
 * margin, and the tightest subject decides the pipeline.
 *
 * Both are stated at a stage's OWN input, in that stage's own units, because that is what its
 * benchmark measures and converting them to a shared unit is where the errors have crept in before.
 */

export interface Floor {
    /** Size at which the detector reliably finds the subject, at the detector's own input. */
    detectedAt: number
    /** Size at which a person can still take PII from the subject, in the STORED image. */
    readableAt: number
    unit: string
    /** How both numbers were obtained, so a reader can re-run rather than trust them. */
    measuredBy: string
}

/**
 * Text is the binding subject and the best measured.
 *
 * Detection: `npm run glyph-floor` sweeps rendered size against a fixed frame. DBNet starts finding
 * text at about 4.9px and has every line by 7px, at the model input.
 *
 * Readability: rendered samples at a range of sizes, judged by eye. 4px is readable, 3px is not, so
 * 3px is where it stops carrying PII. Tesseract gives up at 8-9px and is not the bar: a person reads
 * well past where OCR does, and using OCR as the proxy hid a live leak once already.
 */
export const TEXT_FLOOR: Floor = {
    detectedAt: 7,
    readableAt: 3,
    unit: 'font-size px (ink is about 0.72x this)',
    measuredBy: 'dev/glyph-floor.ts, plus a human judgement on rendered samples',
}

/**
 * Faces, from `dev/floors.ts`: a subject placed at a range of sizes, detected at the detection
 * resolution and re-detected in the artifact.
 *
 * Reliable detection lands around 43px at YuNet's own input; a face is still findable in the
 * artifact down to about 21px. The readable figure uses YuNet-on-the-artifact as the stand-in for
 * re-identification, which is stricter than a person recognising someone and so errs safe.
 */
export const FACE_FLOOR: Floor = {
    detectedAt: 43,
    readableAt: 21,
    unit: 'face px at the stage input',
    measuredBy: 'dev/floors.ts',
}

/**
 * Codes are the loosest by a wide margin: zxing finds them from about 96px while a code has to reach
 * roughly 61px in the artifact before it decodes at all. A code too degraded to decode carries
 * nothing, which makes this subject self-limiting rather than a constraint on the pipeline.
 */
export const CODE_FLOOR: Floor = {
    detectedAt: 96,
    readableAt: 61,
    unit: 'code px at the stage input',
    measuredBy: 'dev/floors.ts',
}

export const FLOORS = { text: TEXT_FLOOR, face: FACE_FLOOR, code: CODE_FLOOR } as const
export type Subject = keyof typeof FLOORS

/** How much larger a subject must be at this detector than in the artifact, for anything readable to
 *  have been detectable. */
export function requiredRatio(floor: Floor): number {
    return floor.detectedAt / floor.readableAt
}

/**
 * The ratio the whole pipeline has to satisfy: the tightest subject, since the guarantee is only as
 * good as the detector with the least room. Text is currently the binding one at 2.33.
 */
export function bindingRatio(): number {
    return Math.max(...Object.values(FLOORS).map(requiredRatio))
}
