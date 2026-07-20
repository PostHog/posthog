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

import { numFromEnv } from './env.ts'
import { type Box, roundTo32 } from './geometry.ts'
import { type Src, srcSharp } from './src-image.ts'

export interface DetectOpts {
    detLimit?: number // detection budget SIDE: the model input is capped at detLimit^2 px (aspect preserved). Bigger = catches smaller text, slower.
    probThreshold?: number // per-pixel text probability cutoff
    boxScoreMin?: number // mean probability over a component's core pixels to keep it
    minAreaPx?: number // min component size in model-resolution px
    dilateX?: number // horizontal dilation radius (model-res px) to merge words on a line
    padX?: number
    padY?: number
}

const DEFAULTS: Required<DetectOpts> = {
    detLimit: numFromEnv('DET_LIMIT', 640, 256, 4096),
    probThreshold: numFromEnv('PROB_T', 0.3, 0.05, 0.9),
    boxScoreMin: numFromEnv('BOX_SCORE', 0.5, 0.05, 0.95),
    minAreaPx: numFromEnv('MIN_AREA', 16, 1, 1024),
    dilateX: numFromEnv('DILATE_X', 6, 0, 64),
    padX: numFromEnv('PAD_X', 0.25, 0, 2),
    padY: numFromEnv('PAD_Y', 0.3, 0, 2),
}

const MEAN = [0.485, 0.456, 0.406]
const STD = [0.229, 0.224, 0.225]

export interface DbnetModel {
    session: ort.InferenceSession
    inputName: string
    outputName: string
}

// 1 intra-op thread by default so we scale by running many images in parallel (one core each).
const ORT_THREADS = numFromEnv('ORT_THREADS', 1, 1, 32)

export async function loadDbnet(modelPath: string): Promise<DbnetModel> {
    const session = await ort.InferenceSession.create(modelPath, {
        graphOptimizationLevel: 'all',
        intraOpNumThreads: ORT_THREADS,
        interOpNumThreads: 1,
        executionMode: 'sequential',
    })
    return { session, inputName: session.inputNames[0], outputName: session.outputNames[0] }
}

async function preprocess(
    src: Src,
    W: number,
    H: number,
    detLimit: number
): Promise<{ data: Float32Array; rw: number; rh: number; sx: number; sy: number }> {
    // Area budget (detLimit^2), aspect preserved: same tensor-size bound as a detLimit-square, but a
    // tall page keeps its native text size instead of being squashed below detectability.
    const ratio = Math.min(1, Math.sqrt((detLimit * detLimit) / (W * H)))
    const rw = roundTo32(W * ratio)
    const rh = roundTo32(H * ratio)
    const { data } = await srcSharp(src).resize(rw, rh, { fit: 'fill' }).raw().toBuffer({ resolveWithObject: true })
    const chw = new Float32Array(3 * rw * rh)
    const plane = rw * rh
    for (let i = 0, p = 0; i < data.length; i += 3, p++) {
        chw[p] = (data[i] / 255 - MEAN[0]) / STD[0]
        chw[plane + p] = (data[i + 1] / 255 - MEAN[1]) / STD[1]
        chw[2 * plane + p] = (data[i + 2] / 255 - MEAN[2]) / STD[2]
    }
    return { data: chw, rw, rh, sx: W / rw, sy: H / rh }
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
    W: number,
    H: number,
    opts: DetectOpts = {}
): Promise<Box[]> {
    const o: Required<DetectOpts> = { ...DEFAULTS, ...opts }
    const { data, rw, rh, sx, sy } = await preprocess(src, W, H, o.detLimit)
    const tensor = new ort.Tensor('float32', data, [1, 3, rh, rw])
    const out = await model.session.run({ [model.inputName]: tensor })
    const prob = out[model.outputName].data as Float32Array
    return postprocess(prob, rw, rh, sx, sy, W, H, o)
}
