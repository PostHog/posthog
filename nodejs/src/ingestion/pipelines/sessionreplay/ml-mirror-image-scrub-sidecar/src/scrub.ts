/**
 * The image-scrub pipelines. Two entry points over the same input so throughput stays comparable:
 *  - blurOnly:  the cheap baseline (downsample + gaussian blur), kept in sync with the inline
 *               anonymizer's rust/replay-anonymizer-node/src/blur.rs so comparisons are apples-to-apples.
 *  - advancedScrub: NSFW/gore gate -> faces, text regions, and QR/barcodes solid-filled.
 *
 * All three models (safety gate, YuNet faces, DBNet text) run on native onnxruntime-node —
 * deliberately ONE ML runtime, so there is a single native-binary compatibility surface and no
 * second runtime with its own failure modes or slow fallback backend. QR/barcode detection runs on
 * zxing-wasm. The source is decoded once to raw RGB (area-capped at SCRUB_MAX_PIXELS) and shared
 * across stages.
 */
import sharp from 'sharp'

import { BLANK_PNG, LIMIT_INPUT_PIXELS, UndecodableImageError, blurOnly } from './blur.ts'
import { type DbnetModel, detectTextDbnet, loadDbnet } from './dbnet.ts'
import { numFromEnv } from './env.ts'
import { type Box } from './geometry.ts'
import { detectCodes } from './qr.ts'
import { type SafetyModel, classifySafety, loadSafety } from './safety.ts'
import { type Src, decodeSrc, srcSharp } from './src-image.ts'
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
    faces: number
    textBoxes: number
    codes: number
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
// Detection budget as a fraction of the image's own scale (sqrt of its area). 0.75 clears all crisp
// rendered UI (session replay's actual domain) cheaply; raise toward 1.0 for faint/small
// scanned-document print (more CPU), lower for more throughput. Faint low-contrast text is
// contrast- not size-limited, so resolution alone won't catch every faded fax line.
const DET_FACTOR = numFromEnv('DET_FACTOR', 0.75, 0.1, 1)
const DET_CAP = numFromEnv('DET_CAP', 1600, 256, 4096) // cap so retina screenshots don't explode
function adaptiveDetLimit(W: number, H: number): number {
    const target = Math.round((Math.sqrt(W * H) * DET_FACTOR) / 32) * 32
    return Math.max(736, Math.min(DET_CAP, target))
}

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
        faces: 0,
        textBoxes: 0,
        codes: 0,
    }
    const t0 = performance.now()
    const tDec = performance.now()
    // Decode the PNG ONCE; every stage re-wraps these raw pixels. The decode is the only stage that
    // consumes untrusted bytes, so its failures are permanent-for-these-bytes (422/skip), never 500.
    let src: Src
    try {
        src = await decodeSrc(input)
    } catch (e) {
        throw e instanceof UndecodableImageError ? e : new UndecodableImageError(String(e))
    }
    const { W, H } = src
    timings.decodeMs = performance.now() - tDec

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
    const det = adaptiveDetLimit(W, H)
    const runText = (): Promise<Box[]> =>
        textMode === 'dbnet' ? detectTextDbnet(m.dbnet, src, W, H, { detLimit: det }) : detectTextRegions(input, W, H)
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

    const out = await compose(src, W, H, fillBoxes, timings)
    timings.totalMs = performance.now() - t0
    return { out, t: timings }
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
async function compose(src: Src, W: number, H: number, boxes: Box[], timings: StageTimings): Promise<Buffer> {
    const tC = performance.now()
    if (boxes.length === 0) {
        timings.composeMs = performance.now() - tC
        const tE0 = performance.now()
        const out0 = await srcSharp(src).png({ compressionLevel: PNG_LEVEL }).toBuffer()
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
    const overlay = await sharp(redBlurred, raw3).joinChannel(alphaLayer, raw1).png().toBuffer()

    timings.composeMs = performance.now() - tC
    const tE = performance.now()
    const out = await srcSharp(src)
        .composite([{ input: overlay, left: 0, top: 0 }])
        .png({ compressionLevel: PNG_LEVEL })
        .toBuffer()
    timings.encodeMs = performance.now() - tE
    return out
}
