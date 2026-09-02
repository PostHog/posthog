/**
 * DBNet text-region detection via onnxruntime-node (native). Model: PP-OCRv3 detection (a DB head),
 * ~2.4MB ONNX. Outputs a per-pixel text-probability map; we threshold it, horizontally dilate it
 * (so words on a line bridge into one box that reaches the line end), find connected components,
 * and return their expanded axis-aligned boxes. Axis-aligned is enough since we only blur.
 *
 * detectTextDbnet takes per-call opts so the same model can run a cheap production pass and an
 * expensive high-recall verification pass (see verify.ts) in the same process.
 */
import * as ort from 'onnxruntime-node'

import { ORT_THREADS } from './cores.ts'
import { numFromEnv } from './env.ts'
import { type Box } from './geometry.ts'
import { type Dims } from './scale-plan.ts'
import { type Src, srcSharp } from './src-image.ts'

export interface DetectOpts {
    probThreshold?: number // per-pixel text probability cutoff
    boxScoreMin?: number // mean probability over a component's core pixels to keep it
    minAreaPx?: number // min component size in model-resolution px
    dilateX?: number // horizontal dilation radius (model-res px) to merge words on a line
    padX?: number
    padY?: number
}

const DEFAULTS: Required<DetectOpts> = {
    probThreshold: numFromEnv('PROB_T', 0.3, 0.05, 0.9),
    boxScoreMin: numFromEnv('BOX_SCORE', 0.5, 0.05, 0.95),
    minAreaPx: numFromEnv('MIN_AREA', 16, 1, 1024),
    dilateX: numFromEnv('DILATE_X', 6, 0, 64),
    padX: numFromEnv('PAD_X', 0.25, 0, 2),
    padY: numFromEnv('PAD_Y', 0.3, 0, 2),
}

/** Unsharp radius applied to the detector's input. 0 disables it. Detection only: the stored image
 *  is never sharpened. */
const DET_SHARPEN = numFromEnv('DET_SHARPEN', 1, 0, 10)

/** Only sharpen once the model's input is this fraction of the ORIGINAL image's side or smaller,
 *  measured across both downscales together (the SCRUB_MAX_PIXELS cap and the detLimit budget).
 *  Sharpening restores edges a resample removed, so on a frame that was barely resampled there is
 *  nothing to restore and it only amplifies whatever noise the source already had, which costs
 *  recall on grainy scans. */
const DET_SHARPEN_BELOW = numFromEnv('DET_SHARPEN_BELOW', 0.6, 0.05, 1)

const MEAN = [0.485, 0.456, 0.406]
const STD = [0.229, 0.224, 0.225]

export interface DbnetModel {
    session: ort.InferenceSession
    inputName: string
    outputName: string
}

export async function loadDbnet(modelPath: string): Promise<DbnetModel> {
    const session = await ort.InferenceSession.create(modelPath, {
        graphOptimizationLevel: 'all',
        intraOpNumThreads: ORT_THREADS,
        interOpNumThreads: 1,
        executionMode: 'sequential',
        // The arena allocator holds on to peak allocations for reuse, which on a pool of workers each
        // running their own sessions is memory multiplied by the worker count: measured at 719MB per
        // worker with it on against 570MB off, on a 2 MP frame. It buys no measurable CPU here
        // (97.6% of baseline over the eval corpus, inside run-to-run noise), so the memory is free.
        enableCpuMemArena: false,
    })
    return { session, inputName: session.inputNames[0], outputName: session.outputNames[0] }
}

async function preprocess(
    src: Src,
    text: { content: Dims; canvas: Dims }
): Promise<{ data: Float32Array; rw: number; rh: number; sx: number; sy: number }> {
    const { width: cw, height: ch } = text.content
    const { width: rw, height: rh } = text.canvas
    // A resample is a low-pass filter, and glyph edges are the high frequencies DB scores. Restoring
    // some of that edge contrast before the model sees it is the cheapest lever on small text.
    // Measured against the ORIGINAL rather than the decoded frame, because both downscales cost edge
    // detail and a 4K screenshot has been through both by the time it arrives here.
    const totalRatio = Math.sqrt((cw * ch) / src.inputPixels)
    // Padding is mid-grey rather than black or white: a flat extreme against a light or dark frame
    // edge is itself a strong edge, which is what the DB head scores.
    const pipeline = srcSharp(src)
        .resize(cw, ch, { fit: 'fill' })
        .extend({ right: rw - cw, bottom: rh - ch, background: '#808080' })
    const sharpened = DET_SHARPEN > 0 && totalRatio < DET_SHARPEN_BELOW
    const { data } = await (sharpened ? pipeline.sharpen({ sigma: DET_SHARPEN }) : pipeline)
        .raw()
        .toBuffer({ resolveWithObject: true })
    const chw = new Float32Array(3 * rw * rh)
    const plane = rw * rh
    for (let i = 0, p = 0; i < data.length; i += 3, p++) {
        chw[p] = (data[i] / 255 - MEAN[0]) / STD[0]
        chw[plane + p] = (data[i + 1] / 255 - MEAN[1]) / STD[1]
        chw[2 * plane + p] = (data[i + 2] / 255 - MEAN[2]) / STD[2]
    }
    return { data: chw, rw, rh, sx: src.W / cw, sy: src.H / ch }
}

/** Horizontal dilation by radius k via per-row prefix sums; bridges inter-word gaps on a line. */
function dilateHoriz(bin: Uint8Array, rw: number, rh: number, k: number): Uint8Array {
    if (k <= 0) {
        return bin
    }
    const out = new Uint8Array(rw * rh)
    const prefix = new Int32Array(rw + 1)
    for (let y = 0; y < rh; y++) {
        const row = y * rw
        for (let x = 0; x < rw; x++) {
            prefix[x + 1] = prefix[x] + bin[row + x]
        }
        for (let x = 0; x < rw; x++) {
            const lo = Math.max(0, x - k)
            const hi = Math.min(rw - 1, x + k)
            out[row + x] = prefix[hi + 1] - prefix[lo] > 0 ? 1 : 0
        }
    }
    return out
}

function postprocess(
    prob: Float32Array,
    rw: number,
    rh: number,
    sx: number,
    sy: number,
    W: number,
    H: number,
    o: Required<DetectOpts>
): Box[] {
    const bin = new Uint8Array(rw * rh)
    for (let i = 0; i < prob.length; i++) {
        bin[i] = prob[i] >= o.probThreshold ? 1 : 0
    }
    const dil = dilateHoriz(bin, rw, rh, o.dilateX)

    const seen = new Uint8Array(rw * rh)
    const stack: number[] = []
    const boxes: Box[] = []
    for (let start = 0; start < dil.length; start++) {
        if (!dil[start] || seen[start]) {
            continue
        }
        let minX = rw,
            minY = rh,
            maxX = 0,
            maxY = 0
        let coreSum = 0,
            coreCnt = 0 // score only over real (pre-dilation) text pixels
        stack.push(start)
        seen[start] = 1
        while (stack.length) {
            const idx = stack.pop()!
            const x = idx % rw
            const y = (idx - x) / rw
            if (bin[idx]) {
                coreSum += prob[idx]
                coreCnt++
            }
            if (x < minX) {
                minX = x
            }
            if (x > maxX) {
                maxX = x
            }
            if (y < minY) {
                minY = y
            }
            if (y > maxY) {
                maxY = y
            }
            if (x > 0 && dil[idx - 1] && !seen[idx - 1]) {
                seen[idx - 1] = 1
                stack.push(idx - 1)
            }
            if (x < rw - 1 && dil[idx + 1] && !seen[idx + 1]) {
                seen[idx + 1] = 1
                stack.push(idx + 1)
            }
            if (y > 0 && dil[idx - rw] && !seen[idx - rw]) {
                seen[idx - rw] = 1
                stack.push(idx - rw)
            }
            if (y < rh - 1 && dil[idx + rw] && !seen[idx + rw]) {
                seen[idx + rw] = 1
                stack.push(idx + rw)
            }
        }
        if (coreCnt < o.minAreaPx || coreSum / coreCnt < o.boxScoreMin) {
            continue
        }
        const ex = (maxX - minX + 1) * o.padX
        const ey = (maxY - minY + 1) * o.padY
        // min/max are inclusive pixel indices, so the box spans [min, max + 1) before padding.
        const left = Math.max(0, Math.round((minX - ex) * sx))
        const top = Math.max(0, Math.round((minY - ey) * sy))
        const right = Math.min(W, Math.round((maxX + 1 + ex) * sx))
        const bottom = Math.min(H, Math.round((maxY + 1 + ey) * sy))
        if (right - left >= 2 && bottom - top >= 2) {
            boxes.push({ left, top, width: right - left, height: bottom - top })
        }
    }
    return boxes
}

export async function detectTextDbnet(
    model: DbnetModel,
    src: Src,
    text: { content: Dims; canvas: Dims },
    opts: DetectOpts = {}
): Promise<Box[]> {
    const o: Required<DetectOpts> = { ...DEFAULTS, ...opts }
    const { data, rw, rh, sx, sy } = await preprocess(src, text)
    const tensor = new ort.Tensor('float32', data, [1, 3, rh, rw])
    const out = await model.session.run({ [model.inputName]: tensor })
    const prob = out[model.outputName].data as Float32Array
    return postprocess(prob, rw, rh, sx, sy, src.W, src.H, o)
}
