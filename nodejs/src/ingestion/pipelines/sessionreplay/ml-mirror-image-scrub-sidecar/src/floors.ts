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
 * Detection: `tsx dev/glyph-floor.ts` sweeps rendered size against a fixed frame. DBNet starts finding
 * text at about 4.9px and has every line by 7px, at the model input.
 *
 * Readability: rendered samples at a range of sizes, judged by eye. 4px is readable and 3px is not,
 * so 3px is the largest size that carries nothing, which is the conservative end of that boundary. Tesseract gives up at 8-9px and is not the bar: a person reads
 * well past where OCR does, and using OCR as the proxy hid a live leak once already.
 */
export const TEXT_FLOOR: Floor = {
    detectedAt: 7,
    readableAt: 3,
    unit: 'font-size px (ink is about 0.72x this)',
    measuredBy: 'dev/glyph-floor.ts, plus a human judgement on rendered samples',
}

/**
 * Faces, from `dev/floors.ts`. Both numbers are converted from the sweep's source-pixel column, and
 * the arithmetic is written out because getting these two into the same frame is exactly where the
 * previous version went wrong: it paired a figure measured at the detection frame with one measured
 * in the artifact and called the ratio 43/21.
 *
 * The sweep runs at 0.9 MP detection and 0.1 MP storage from a 1920x1080 source, so a face of S
 * source px reaches YuNet at S x sqrt(0.9/2.07) x (640/1265) = 0.333 S, and is kept in the artifact
 * at S x sqrt(0.1/2.07) = 0.220 S.
 *
 * Every face is found at 192 source px, which is 64px at YuNet's input. A face is still findable in
 * the artifact at 96 source px, which is 21px there. The readable figure uses YuNet-on-the-artifact
 * as the stand-in for re-identification, which is stricter than a person recognising someone.
 */
export const FACE_FLOOR: Floor = {
    detectedAt: 64,
    readableAt: 21,
    unit: "face px, detected at YuNet's own input, readable in the stored image",
    measuredBy: 'dev/floors.ts: a face placed at 24-192px in a 1920x1080 source',
}

/**
 * Codes, in multiples of a code's size in the stored image, which is the unit `dev/code-bench.ts`
 * sweeps zxing's input in. The formats need different pixel sizes, both to be found and to be read,
 * so no single pair of pixel sizes holds for all of them.
 *
 * A code counts as readable when zxing decodes it from the stored image at 1x, 2x or 3x, since an
 * attacker can upscale. zxing finds every such code once it reads the frame at 3 times the stored
 * scale. At 2 times it misses two, both Aztec.
 */
export const CODE_FLOOR: Floor = {
    detectedAt: 3,
    readableAt: 1,
    unit: "multiples of a code's size in the stored image",
    measuredBy:
        'dev/code-bench.ts: six codes in five formats, six frame shapes, seven sizes, with blur, rotation and JPEG',
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
 * good as the detector with the least room.
 */
export function bindingRatio(): number {
    return Math.max(...Object.values(FLOORS).map(requiredRatio))
}
