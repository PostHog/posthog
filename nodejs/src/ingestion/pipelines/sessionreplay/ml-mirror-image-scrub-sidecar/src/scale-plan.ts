/**
 * Every resize the scrub performs, decided in one place, before any pixel is touched.
 *
 * The sizing used to be spread across five modules: the decode capped area, the text detector picked
 * a budget and quantised it, the face detector letterboxed into a fixed square, and the storage step
 * divided by a ratio. Each was locally sensible and every serious defect found in review lived in
 * the seams between them, because no single place knew all of it. This is that place. It is pure
 * arithmetic on dimensions, so the whole geometry can be asserted for any shape class without a
 * model, an image, or a millisecond of inference.
 *
 * The rules it encodes, in full:
 *
 *  1. Never upscale. Enlarging pixels adds nothing and softens the edges detection depends on. The
 *     one exception is a detector whose input size is fixed by its model, which is a property of the
 *     model rather than a choice, and is marked as such.
 *  2. Bound the work by the tensor, not by the frame. A budget on frame area does not bound the
 *     tensor once a collapsed axis is padded up to the encoder's stride.
 *  3. Store small. The final consumer identifies what kind of site a session is on, so it needs
 *     scene structure and not legibility. Text being unreadable in the artifact is the point.
 *  4. Keep the ratio. Every detector must see a subject at least `ratio` times larger than the
 *     stored image keeps it, so anything still readable was large enough to have been found.
 */
import { LIMIT_INPUT_PIXELS } from './blur.ts'
import { numFromEnv } from './env.ts'
import { bindingRatio } from './floors.ts'

export interface Dims {
    width: number
    height: number
}

export interface ScalePlan {
    /** The frame every stage shares, decoded once. */
    frame: Dims
    /** What DBNet sees: content, and the stride-padded canvas that is actually allocated. */
    text: { content: Dims; canvas: Dims }
    /** What YuNet sees. Its input is a fixed square, so this is how much of the frame reaches it. */
    face: { scale: number }
    /** What zxing sees. It works on the frame directly. */
    code: { scale: number }
    /** What gets written, and is the only copy that exists. */
    stored: Dims
}

export interface PlanLimits {
    /** Aspect past which the face detector tiles rather than letterboxing the whole frame, and the
     *  aspect of each tile. The planner has to know these: modelling the detector as a single
     *  letterbox understates how much of a long frame it really sees. */
    faceTileAbove: number
    faceTileAspect: number
    /** Area budget for the decoded frame. */
    framePixels: number
    /** Area budget for the text detector's padded canvas. */
    textCanvasPixels: number
    /** Upper bound on the stored image; the ratio may make it smaller still. */
    storedPixels: number
    /** The fixed square YuNet's build requires. */
    faceInputSide: number
    /** Stride the text encoder needs its input to be a multiple of. */
    stride: number
    /** Margin over the measured floors. 1 means exactly what the measurement supports. */
    safetyFactor: number
}

const atLeastOne = (n: number): number => Math.max(1, Math.floor(n))

/** Floor for the decoded frame, named once so the derived default and its own validation cannot
 *  disagree, which is how a legal stored size produced an illegal frame size. */
const MIN_FRAME_PIXELS = 96 * 96

/** The face detector's tiling rule, owned here because the plan has to model it. yunet.ts imports
 *  these rather than declaring its own, so the model and the plan cannot disagree. */
export const FACE_TILE_ABOVE = 3
export const FACE_TILE_ASPECT = 6

/**
 * Most inferences one image may spend on faces.
 *
 * Tiling covers a long frame with overlapping windows, and the count grows with the aspect ratio,
 * which the frame's AREA budget does not bound: a 400000x4 source plans a 280149x2 frame and asks for
 * 28,015 inferences from about 100 KB of PNG. Past the cap the windows widen instead of multiplying,
 * so coverage is kept and the subject shrinks at the model, which is the same trade the area budget
 * makes everywhere else.
 */
export const FACE_MAX_WINDOWS = 12

/** Window length along the long axis, given the tiling rule and the inference cap. Shared by the
 *  planner and the detector so one rule produces both the plan and the work. */
export function faceWindowLong(long: number, short: number, tileAbove: number, tileAspect: number): number {
    if (long / short <= tileAbove) {
        return long
    }
    // Each window past the first advances by (windowLong - short), so covering `long` within the cap
    // needs at least this much window. Ceiled to an integer: this length becomes a crop rectangle,
    // and sharp rejects a fractional one, so a fraction here is a 500 on every extreme-aspect image
    // rather than a rounding difference. Up rather than down, so the cap still holds.
    const toFitCap = Math.ceil((long - short) / FACE_MAX_WINDOWS + short)
    return Math.min(long, Math.max(tileAspect * short, toFitCap))
}

/** Scale that fits `dims` inside an area budget, never above 1 because rule 1 forbids upscaling. */
export function scaleToArea(dims: Dims, budgetPixels: number): number {
    return Math.min(1, Math.sqrt(budgetPixels / (dims.width * dims.height)))
}

export function applyScale(dims: Dims, scale: number): Dims {
    return { width: atLeastOne(dims.width * scale), height: atLeastOne(dims.height * scale) }
}

/**
 * Scale into an area budget and stay there.
 *
 * `applyScale` alone does not: an axis that scales below one pixel is floored to one, which leaves
 * the other axis at its full scaled length and the product above the budget by any factor. A
 * 1x50,000,000 source, a few hundred KB of PNG, plans a 1x4,796,123 frame at ten times the budget,
 * and the per-worker memory model is derived from that budget. Clamp the long axis against the
 * floored short one.
 */
export function fitToArea(dims: Dims, budgetPixels: number): Dims {
    const scaled = applyScale(dims, scaleToArea(dims, budgetPixels))
    if (scaled.width * scaled.height <= budgetPixels) {
        return scaled
    }
    return scaled.width >= scaled.height
        ? { ...scaled, width: atLeastOne(budgetPixels / scaled.height) }
        : { ...scaled, height: atLeastOne(budgetPixels / scaled.width) }
}

const upToStride = (n: number, stride: number): number => Math.max(stride, Math.ceil(n / stride) * stride)

/**
 * Content dimensions and the stride-padded canvas around them, with the CANVAS bounded rather than
 * the content.
 *
 * Padding rather than resizing to reach the stride, because resizing up enlarges real pixels and
 * resizing down discards rows, which on a short banner is a large fraction of it. But padding a
 * collapsed axis multiplies the area back: a 212132x2 frame pads to 212160x32, so an area budget on
 * the content alone lets a 100 KB source allocate a multi-megapixel tensor. Shrink the long axis
 * against the short one's padded size until the canvas itself fits.
 */
export function fitToCanvas(dims: Dims, budgetPixels: number, stride: number): { content: Dims; canvas: Dims } {
    let content = fitToArea(dims, budgetPixels)
    let canvas = { width: upToStride(content.width, stride), height: upToStride(content.height, stride) }
    for (let guard = 0; guard < 4 && canvas.width * canvas.height > budgetPixels; guard++) {
        if (canvas.width >= canvas.height) {
            const width = Math.max(stride, Math.floor(budgetPixels / canvas.height / stride) * stride)
            content = { ...content, width: Math.min(content.width, width) }
            canvas = { ...canvas, width: upToStride(content.width, stride) }
        } else {
            const height = Math.max(stride, Math.floor(budgetPixels / canvas.width / stride) * stride)
            content = { ...content, height: Math.min(content.height, height) }
            canvas = { ...canvas, height: upToStride(content.height, stride) }
        }
    }
    return { content, canvas }
}

/**
 * How much of the frame the face detector sees.
 *
 * Scaling the long side to fill the square maximises the subject at the model, which is what recall
 * wants, so enlarging a frame smaller than the square is deliberate and allowed by rule 1: the size
 * is the model's, not ours. What matters here is only the reduction, since that is what narrows the
 * ratio.
 *
 * It tiles rather than letterboxing once a frame is longer than `tileAbove`, so the scale is set by
 * the TILE and not by the whole frame. Modelling it as a single letterbox understated the scale on
 * every long frame, and because the stored size is derived from the weakest detector that understating
 * crushed the artifact: an 8000x60 banner planned a 1px-tall image where the real geometry supports
 * nineteen, for a guarantee that never asked for it.
 */
export function faceInputScale(dims: Dims, side: number, tileAbove: number, tileAspect: number): number {
    const long = Math.max(dims.width, dims.height)
    const short = Math.min(dims.width, dims.height)
    return Math.min(1, side / faceWindowLong(long, short, tileAbove, tileAspect))
}

/**
 * The plan for one source image.
 *
 * The stored size is derived from the WEAKEST detector rather than any single one: a guarantee that
 * holds for the text detector and not the face detector is not a guarantee. Every reduction between
 * the source and each detector is already folded into its scale, so the ratio is enforced against
 * what each model really saw rather than against the budgets that were asked for.
 */
export function planScales(source: Dims, limits: PlanLimits): ScalePlan {
    const frame = fitToArea(source, limits.framePixels)
    const text = fitToCanvas(frame, limits.textCanvasPixels, limits.stride)
    const faceScale = faceInputScale(frame, limits.faceInputSide, limits.faceTileAbove, limits.faceTileAspect)

    // Each detector's scale relative to the frame, so they are comparable.
    const textScale = Math.min(text.content.width / frame.width, text.content.height / frame.height)
    const weakest = Math.min(textScale, faceScale, 1)

    const ratio = bindingRatio() * limits.safetyFactor
    const stored = applyScale(frame, Math.min(1, weakest / ratio, scaleToArea(frame, limits.storedPixels)))
    return {
        frame,
        text,
        face: { scale: faceScale },
        code: { scale: 1 },
        stored,
    }
}

/**
 * The limits this deployment runs with.
 *
 * Only the stored size is an operator's choice. Everything else follows from it: the detectors have
 * to see enough to keep the ratio, and the frame has to carry enough for the detectors. Exposing the
 * others as independent knobs is what let a pair of individually-reasonable settings combine into a
 * pipeline that under-redacted.
 */
export function limitsFromEnv(): PlanLimits {
    const storedPixels = numFromEnv('SCRUB_OUT_MAX_PIXELS', 50_000, 16 * 16, LIMIT_INPUT_PIXELS)
    const safetyFactor = numFromEnv('SCRUB_SAFETY_FACTOR', 1.3, 1, 4)
    // The frame has to carry the ratio for the tightest subject, with the margin, or no detector can
    // satisfy it however the later stages are sized.
    const needed = storedPixels * (bindingRatio() * safetyFactor) ** 2
    return {
        // Clamped at BOTH ends: numFromEnv validates a default as strictly as an override, so a
        // legal storedPixels must never derive an illegal framePixels and hand the operator a refusal
        // naming a variable they never set. Only the upper end was clamped, so every stored size
        // under about 1000 px crash-looped the sidecar before it bound a listener.
        framePixels: numFromEnv(
            'SCRUB_MAX_PIXELS',
            Math.max(MIN_FRAME_PIXELS, Math.min(LIMIT_INPUT_PIXELS, Math.ceil(needed))),
            MIN_FRAME_PIXELS,
            LIMIT_INPUT_PIXELS
        ),
        textCanvasPixels: numFromEnv('DET_CANVAS_PIXELS', 736 * 736, 256 * 256, 4096 * 4096),
        storedPixels,
        faceInputSide: 640,
        faceTileAbove: FACE_TILE_ABOVE,
        faceTileAspect: FACE_TILE_ASPECT,
        stride: 32,
        safetyFactor,
    }
}
