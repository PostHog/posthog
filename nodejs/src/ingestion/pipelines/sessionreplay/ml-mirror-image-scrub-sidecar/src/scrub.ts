/**
 * The image-scrub pipelines. Two entry points over the same input so throughput stays comparable:
 *  - blurOnly:  the cheap baseline (downsample + gaussian blur), kept in sync with the inline
 *               anonymizer's rust/replay-anonymizer/src/blur.rs so comparisons are apples-to-apples.
 *  - advancedScrub: NSFW/gore gate -> faces, text regions, and QR/barcodes solid-filled.
 *
 * All three models (safety gate, YuNet faces, DBNet text) run on native onnxruntime-node —
 * deliberately ONE ML runtime, so there is a single native-binary compatibility surface and no
 * second runtime with its own failure modes or slow fallback backend. QR/barcode detection runs on
 * zxing-wasm. The source is decoded once to raw RGB (area-capped at SCRUB_MAX_PIXELS) and shared
 * across stages.
 */
import sharp, { type Sharp } from 'sharp'

import { BLANK_PNG, LIMIT_INPUT_PIXELS, blurOnly } from './blur.ts'
import { type DbnetModel, detectTextDbnet, loadDbnet } from './dbnet.ts'
import { numFromEnv } from './env.ts'
import { type Box } from './geometry.ts'
import { PermanentImageError, undecodableImageErrorFromDecodeFailure } from './image-input.ts'
import { detectCodes } from './qr.ts'
import { type SafetyModel, classifySafety, loadSafety } from './safety.ts'
import { type Dims, type ScalePlan, limitsFromEnv, planScales } from './scale-plan.ts'
import { type Src, decodeSrc, probeDims, srcSharp } from './src-image.ts'
import { type YunetModel, detectFacesYunet, loadYunet } from './yunet.ts'

export type TextMode = 'heuristic' | 'dbnet'

// blurOnly/BLANK_PNG live in the ML-dep-free blur.ts; re-exported here so the eval harness and
// benchmarks can compare the baseline against advancedScrub from one module.
export { BLANK_PNG, blurOnly }

// --- models -------------------------------------------------------------------------------------
export interface Models {
    safety: SafetyModel
    dbnet: DbnetModel
    yunet: YunetModel
}

export async function loadModels(
    dbnetPath = 'models/dbnet_det.onnx',
    yunetPath = 'models/yunet.onnx',
    safetyPath = 'models/safety.onnx'
): Promise<Models> {
    const [safety, dbnet, yunet] = await Promise.all([
        loadSafety(safetyPath),
        loadDbnet(dbnetPath),
        loadYunet(yunetPath),
    ])
    return { safety, dbnet, yunet }
}

// For harnesses that load and drop models repeatedly (dev/bench.ts). The sidecar never calls it:
// models live as long as the worker that loaded them, and every path that ends a worker has either
// already lost the thread or cannot get a reply from it, so the isolate teardown after
// worker.terminate() is what frees the sessions there.
export async function disposeModels(m: Models): Promise<void> {
    await Promise.all([m.safety.session.release(), m.dbnet.session.release(), m.yunet.session.release()])
}

// --- advanced pipeline --------------------------------------------------------------------------
export interface StageTimings {
    decodeMs: number
    nsfwMs: number
    faceMs: number
    textMs: number
    codesMs: number
    composeMs: number
    encodeMs: number
    totalMs: number
    blanked: boolean
    /** Frame was a single flat colour, so detection was skipped as provably vacuous. */
    uniform: boolean
    faces: number
    textBoxes: number
    codes: number
    /** Source format and its pre-downscale size: which stage to attack depends on the corpus mix,
     *  and only formats with a multi-resolution decode can be shrunk on load. */
    format: string
    inputPixels: number
    /** Encoded size as received, which is what this image cost the topic and the bucket. */
    inputBytes: number
    /** Pixels actually written, which SCRUB_OUT_MAX_PIXELS can move independently of the source. */
    storedPixels: number
}

const NSFW_THRESHOLD = numFromEnv('NSFW_THRESHOLD', 0.6, 0.05, 0.95) // NSFL+NSFW combined; deliberately loose, this is a safety net
const PNG_LEVEL = numFromEnv('PNG_LEVEL', 3, 0, 9) // sharp png compressionLevel; lower = faster, bigger
// Every redaction (faces, text, codes) is a SOLID mean-colour fill (irreversible) rather than a
// blur/mosaic (low-pass filters that leave coarse structure an LLM or a re-run detector can still
// recover). Text margin scales with box height — our horizontal-only dilation makes each box one
// line, so its height is a font-size proxy — so big titles get a big margin. Edges are feathered so
// the fill isn't a jarring hard rectangle.
const TEXT_MARGIN_FRAC = numFromEnv('TEXT_MARGIN_FRAC', 0.25, 0, 2) // top/side margin as a fraction of box height
const TEXT_MARGIN_BOTTOM_FRAC = numFromEnv('TEXT_MARGIN_BOTTOM_FRAC', 0.45, 0, 2) // extra below for descenders
const TEXT_MARGIN_MIN = numFromEnv('TEXT_MARGIN_MIN', 4, 0, 64) // floor in px for tiny text
const EDGE_BLUR = numFromEnv('EDGE_BLUR', 4, 0, 32) // sigma to feather redaction-region edges (0 = hard edges; never reveals)

function clampBox(b: Box, W: number, H: number): Box | null {
    const left = Math.max(0, Math.min(W - 1, Math.round(b.left)))
    const top = Math.max(0, Math.min(H - 1, Math.round(b.top)))
    const width = Math.max(1, Math.min(W - left, Math.round(b.width)))
    const height = Math.max(1, Math.min(H - top, Math.round(b.height)))
    if (width < 2 || height < 2) {
        return null
    }
    return { left, top, width, height }
}

// --- input preparation --------------------------------------------------------------------------
/** Adaptive DBNet detection budget: big enough to resolve small text on retina shots, capped for cost.
 *  The returned value is the budget SIDE — dbnet caps its input at detLimit^2 px, aspect preserved. */
/** Whole worker job for one image, advanced path. Detection is parallelized when PARALLEL_DETECT=1:
 *  the three ORT sessions run on onnxruntime's background threads. */
export async function advancedScrub(
    input: Buffer,
    m: Models,
    textMode: TextMode = 'dbnet'
): Promise<{ out: Buffer; t: StageTimings }> {
    const timings: StageTimings = {
        decodeMs: 0,
        nsfwMs: 0,
        faceMs: 0,
        textMs: 0,
        codesMs: 0,
        composeMs: 0,
        encodeMs: 0,
        totalMs: 0,
        blanked: false,
        uniform: false,
        faces: 0,
        textBoxes: 0,
        codes: 0,
        format: 'unknown',
        inputPixels: 0,
        inputBytes: input.length,
        storedPixels: 0,
    }
    const t0 = performance.now()
    const tDec = performance.now()
    // Decode the PNG ONCE; every stage re-wraps these raw pixels. The decode is the only stage that
    // consumes untrusted bytes, so its failures are permanent-for-these-bytes (422/skip), never 500.
    let src: Src
    let plan: ScalePlan
    try {
        const meta = await probeDims(input)
        // One decision, before any pixel is read: every stage below takes its size from here.
        plan = planScales(meta, limitsFromEnv())
        src = await decodeSrc(input, plan.frame)
    } catch (e) {
        throw e instanceof PermanentImageError ? e : undecodableImageErrorFromDecodeFailure(e)
    }
    const { W, H } = src
    timings.decodeMs = performance.now() - tDec
    timings.format = src.format
    timings.inputPixels = src.inputPixels

    // A frame of one exact colour holds no text, face, code or anything the safety gate could trip
    // on, so every model below can only return nothing. Replay captures plenty of them: blank page
    // loads, transitions, cleared views. Ahead of the gate rather than after it because the gate is a
    // fixed-cost inference on every frame, which makes it the largest single thing this skips.
    if (isUniform(src)) {
        timings.uniform = true
        // Stored at the planned size like any other frame. Sizing it by its own dimensions instead
        // would make a blank frame the one image kept at full resolution, which is a surprising
        // exception to carry for no benefit: a flat colour is as recognisable small as large.
        const out = await compose(src, W, H, [], timings, plan.stored)
        timings.totalMs = performance.now() - t0
        return { out, t: timings }
    }

    // 1. NSFW / gore gate FIRST: if it trips we skip all detection. Running it first (rather than
    //    overlapping detection) keeps each worker ~1 core, which packs better under multi-process
    //    scaling — the throughput-bound case. Set PARALLEL_DETECT=1 to overlap instead (lower latency
    //    per image, but each worker uses more cores).
    const tN = performance.now()
    const scores = await classifySafety(m.safety, src)
    const bad = scores.nsfl + scores.nsfw
    timings.nsfwMs = performance.now() - tN
    if (bad >= NSFW_THRESHOLD) {
        timings.blanked = true
        timings.totalMs = performance.now() - t0
        return { out: BLANK_PNG, t: timings }
    }

    // 2. Face (YuNet) + text (DBNet) on native ORT, codes (zxing) on wasm. Serial by default
    //    (1 core/worker); parallel opt-in.
    const runText = (): Promise<Box[]> =>
        textMode === 'dbnet' ? detectTextDbnet(m.dbnet, src, plan.text) : detectTextRegions(input, W, H)
    let faceBoxes: Box[]
    let textBoxes: Box[]
    let codeBoxes: Box[]
    if (process.env.PARALLEL_DETECT === '1') {
        const tD = performance.now()
        ;[faceBoxes, textBoxes, codeBoxes] = await Promise.all([
            detectFacesYunet(m.yunet, src, W, H),
            runText(),
            detectCodes(src),
        ])
        timings.faceMs = timings.textMs = timings.codesMs = performance.now() - tD
    } else {
        const tF = performance.now()
        faceBoxes = await detectFacesYunet(m.yunet, src, W, H)
        timings.faceMs = performance.now() - tF
        const tT = performance.now()
        textBoxes = await runText()
        timings.textMs = performance.now() - tT
        const tQ = performance.now()
        codeBoxes = await detectCodes(src)
        timings.codesMs = performance.now() - tQ
    }
    timings.faces = faceBoxes.length
    timings.textBoxes = textBoxes.length
    timings.codes = codeBoxes.length

    // Text boxes get a font-size-scaled margin (DBNet boxes sit on the baseline, so descenders —
    // g, y, p, q, j — hang below and need extra coverage underneath). Face boxes are already padded
    // by the detector (yunet PAD) and code boxes by detectCodes; they fill as-is.
    const expandText = (t: Box): Box | null => {
        const mg = Math.round(Math.max(TEXT_MARGIN_MIN, t.height * TEXT_MARGIN_FRAC))
        const mb = Math.round(Math.max(TEXT_MARGIN_MIN, t.height * TEXT_MARGIN_BOTTOM_FRAC))
        return clampBox(
            { left: t.left - mg, top: t.top - mg, width: t.width + 2 * mg, height: t.height + mg + mb },
            W,
            H
        )
    }
    const fillBoxes = [...faceBoxes, ...textBoxes.map(expandText).filter((b): b is Box => b !== null), ...codeBoxes]

    const out = await compose(src, W, H, fillBoxes, timings, plan.stored)
    timings.totalMs = performance.now() - t0
    return { out, t: timings }
}

/** Whether every pixel is the same exact colour.
 *
 *  Exact, and over the same buffer every detector is given, which is what makes skipping them sound:
 *  a frame that is one colour at that resolution cannot yield a detection at that resolution. Both
 *  obvious relaxations break that: a tolerance admits a faint watermark, and running it over a
 *  thumbnail admits a single 14px line once the downscale averages it into the background. Costs
 *  nothing on a frame with content, which differs from its first pixel within the first few, and a
 *  full pass only on frames it is about to save an entire detection round on. */
export function isUniform(src: Src): boolean {
    const d = src.data
    const r = d[0]
    const g = d[1]
    const b = d[2]
    for (let i = 3; i < d.length; i += 3) {
        if (d[i] !== r || d[i + 1] !== g || d[i + 2] !== b) {
            return false
        }
    }
    return true
}

/**
 * Model-free text detector. Text has high local edge density, so: downscale to grayscale, compute
 * a gradient map, tile it, and mark tiles whose mean gradient is high (but not saturated, which
 * filters out hard image/photo edges). Returns the texty tiles as boxes in full-res coords. Rough,
 * but we only need "blur where text is", not character-accurate boxes.
 */
const TEXT_DS_WIDTH = 480 // downscale width for the gradient pass
const TEXT_TILE = 10 // tile size in downscaled px
const TEXT_EDGE_T = 22 // mean gradient threshold for a tile to count as text

async function detectTextRegions(input: Buffer, W: number, H: number): Promise<Box[]> {
    const dsW = Math.min(W, TEXT_DS_WIDTH)
    const sx = W / dsW
    const dsH = Math.max(1, Math.round(H / sx))
    const { data, info } = await sharp(input, { limitInputPixels: LIMIT_INPUT_PIXELS })
        .grayscale()
        .resize(dsW, dsH, { fit: 'fill' })
        .raw()
        .toBuffer({ resolveWithObject: true })
    const w = info.width
    const h = info.height
    const cols = Math.ceil(w / TEXT_TILE)
    const rows = Math.ceil(h / TEXT_TILE)
    const sum = new Float64Array(cols * rows)
    const cnt = new Int32Array(cols * rows)
    const sat = new Int32Array(cols * rows) // count of very-strong edges (likely photo/icon, not text)

    for (let y = 1; y < h - 1; y++) {
        const row = y * w
        for (let x = 1; x < w - 1; x++) {
            const i = row + x
            const g = Math.abs(data[i + 1] - data[i - 1]) + Math.abs(data[i + w] - data[i - w])
            const ci = Math.floor(y / TEXT_TILE) * cols + Math.floor(x / TEXT_TILE)
            sum[ci] += g
            cnt[ci]++
            if (g > 200) {
                sat[ci]++
            }
        }
    }

    const boxes: Box[] = []
    for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
            const ci = r * cols + c
            const n = cnt[ci]
            if (n === 0) {
                continue
            }
            const mean = sum[ci] / n
            const satFrac = sat[ci] / n
            if (mean > TEXT_EDGE_T && satFrac < 0.12) {
                const b = clampBox(
                    {
                        left: c * TEXT_TILE * sx,
                        top: r * TEXT_TILE * sx,
                        width: TEXT_TILE * sx,
                        height: TEXT_TILE * sx,
                    },
                    W,
                    H
                )
                if (b) {
                    boxes.push(b)
                }
            }
        }
    }
    return boxes
}

/** Overwrite every redaction box (faces, text, codes alike) with its quantized mean colour on a
 *  copy of the frame, then composite that copy back over the original through a hard alpha mask.
 *  Box-count-independent: one full-frame blur + one composite regardless of box count. The blur
 *  feathers only the fill COLOUR into its surroundings — the alpha stays hard, so no original
 *  pixels inside a box ever survive. A solid fill carries no glyph, face, or code-module structure
 *  (blur and mosaic are low-pass filters whose coarse structure an LLM or a re-run detector can
 *  still recover), so the same irreversible treatment covers all three classes. */
export async function compose(
    src: Src,
    W: number,
    H: number,
    boxes: Box[],
    timings: StageTimings,
    /** Where the plan says this image is stored. Passed in rather than derived here, because the size
     *  is a property of the whole pipeline's geometry and not of the compose step. */
    stored: Dims
): Promise<Buffer> {
    const tC = performance.now()
    if (boxes.length === 0) {
        timings.composeMs = performance.now() - tC
        const tE0 = performance.now()
        const out0 = await encodeStored(srcSharp(src), W, H, stored, timings)
        timings.encodeMs = performance.now() - tE0
        return out0
    }

    // Redaction layer starts as a copy of the source; boxes are OVERWRITTEN rather than low-pass
    // filtered, so their content is destroyed (irreversible), not merely softened. The base frame
    // must stay pristine — outside the mask the composite shows it — which is why the fills go into
    // a copy rather than in place.
    const red = Buffer.from(src.data)
    const alpha = new Uint8Array(W * H)

    for (const b of boxes) {
        let r = 0,
            g = 0,
            bl = 0
        const n = b.width * b.height
        for (let y = b.top; y < b.top + b.height; y++) {
            let idx = (y * W + b.left) * 3
            for (let x = 0; x < b.width; x++, idx += 3) {
                r += src.data[idx]
                g += src.data[idx + 1]
                bl += src.data[idx + 2]
            }
        }
        // Quantize the fill to the top 4 bits per channel (16 levels each, 12 bits total instead of
        // 24) so it carries even less signal about the underlying content's colours.
        r = Math.round(r / n) & 0xf0
        g = Math.round(g / n) & 0xf0
        bl = Math.round(bl / n) & 0xf0
        for (let y = b.top; y < b.top + b.height; y++) {
            let idx = (y * W + b.left) * 3
            for (let x = 0; x < b.width; x++, idx += 3) {
                red[idx] = r
                red[idx + 1] = g
                red[idx + 2] = bl
            }
            alpha.fill(255, y * W + b.left, y * W + b.left + b.width)
        }
    }

    const raw3 = { raw: { width: W, height: H, channels: 3 } } as const
    const raw1 = { raw: { width: W, height: H, channels: 1 } } as const
    const alphaLayer = Buffer.from(alpha.buffer, alpha.byteOffset, alpha.byteLength)

    // Soften edges by blurring the COLOUR layer only (alpha stays hard, so nothing under a box is
    // ever revealed; the blur just fades the fill into its background margin).
    const redBlurred = EDGE_BLUR > 0 ? await sharp(red, raw3).blur(EDGE_BLUR).raw().toBuffer() : red
    // Raw, not PNG: composite reads a raw buffer directly, so encoding here would only be decoded
    // again inside composite, costing a full-frame round-trip at sharp's default compression.
    const overlay = await sharp(redBlurred, raw3).joinChannel(alphaLayer, raw1).raw().toBuffer()

    timings.composeMs = performance.now() - tC
    const tE = performance.now()
    const redacted = srcSharp(src).composite([
        { input: overlay, raw: { width: W, height: H, channels: 4 }, left: 0, top: 0 },
    ])
    const out = await encodeStored(redacted, W, H, stored, timings)
    timings.encodeMs = performance.now() - tE
    return out
}

/**
 * Encode at the storage budget, downscaling only after every fill is already in the pixels.
 *
 * Order matters here and is the whole reason this is a separate step. Resampling the frame first and
 * filling the rescaled boxes afterwards leaves a rim of the content each box exists to destroy: a
 * resize kernel reaches beyond the box edge, so destination pixels just outside it carry a weighted
 * average that includes what was inside. Rounding the boxes outward covers one pixel of rounding,
 * not the kernel's reach, and measured against a black block on white the residue runs to full
 * intensity one pixel out at a mild downscale. Downscaling what is already redacted cannot leak,
 * because the only thing left to smear is the solid fill.
 *
 * Sharp orders resize before composite within one pipeline regardless of call order, so the resize
 * has to happen in a second pass over the composited pixels rather than chained onto the first.
 */
async function encodeStored(
    redacted: Sharp,
    W: number,
    H: number,
    stored: Dims,
    timings?: StageTimings
): Promise<Buffer> {
    const { width: outW, height: outH } = stored
    if (timings) {
        timings.storedPixels = outW * outH
    }
    if (outW >= W && outH >= H) {
        return redacted.png({ compressionLevel: PNG_LEVEL }).toBuffer()
    }
    const { data, info } = await redacted.raw().toBuffer({ resolveWithObject: true })
    return sharp(data, { raw: { width: info.width, height: info.height, channels: info.channels } })
        .resize(outW, outH, { fit: 'fill' })
        .png({ compressionLevel: PNG_LEVEL })
        .toBuffer()
}
