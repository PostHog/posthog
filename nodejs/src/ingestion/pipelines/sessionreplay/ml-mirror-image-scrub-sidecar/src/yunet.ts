/**
 * YuNet face detection via onnxruntime-node (native, async). One multi-scale pass (strides 8/16/32)
 * detects small and large faces at once, so normal-aspect frames need a single inference; only
 * extreme-aspect frames are tiled (see detectionWindows).
 *
 * Decode follows OpenCV's FaceDetectorYN: score = sqrt(cls*obj), grid-anchor bbox, then greedy NMS.
 */
import * as ort from 'onnxruntime-node'

import { numFromEnv } from './env.ts'
import { type Box } from './geometry.ts'
import { type Src, srcSharp } from './src-image.ts'

const YUNET_SIDE = 640 // this YuNet build has a FIXED 640x640 input (dynamic dims are rejected)
const SCORE_MIN = numFromEnv('YUNET_SCORE', 0.7, 0.05, 0.95)
const NMS_IOU = 0.3
const STRIDES = [8, 16, 32]
const PAD = 0.25 // expand each detected face box so hairline/chin/ears are covered
const ORT_THREADS = numFromEnv('ORT_THREADS', 1, 1, 32)

export interface YunetModel {
    session: ort.InferenceSession
    inputName: string
}

export async function loadYunet(modelPath: string): Promise<YunetModel> {
    const session = await ort.InferenceSession.create(modelPath, {
        graphOptimizationLevel: 'all',
        intraOpNumThreads: ORT_THREADS,
        interOpNumThreads: 1,
        executionMode: 'sequential',
    })
    return { session, inputName: session.inputNames[0] }
}

function iou(a: Box, b: Box): number {
    const x1 = Math.max(a.left, b.left)
    const y1 = Math.max(a.top, b.top)
    const x2 = Math.min(a.left + a.width, b.left + b.width)
    const y2 = Math.min(a.top + a.height, b.top + b.height)
    const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1)
    return inter === 0 ? 0 : inter / (a.width * a.height + b.width * b.height - inter)
}

export interface FaceOpts {
    scoreMin?: number // lower = more sensitive (the verification pass uses this to catch lingering faces)
}

// Tiling bounds for extreme-aspect frames. A single letterboxed pass scales by 640/longSide, so on a
// very tall/wide image a face (at most ~shortSide across) can land below the detector's smallest
// stride. Above MAX_ASPECT the frame is cut along its long axis into windows of aspect TILE_ASPECT
// (overlapping by one shortSide, so a face — at most one shortSide across — is always fully inside
// some window): each window then scales by 640/(TILE_ASPECT*shortSide), keeping any face at least
// ~640/TILE_ASPECT/(shortSide/faceSize) px. TILE_ASPECT=6 keeps a face spanning the full short side
// at >=107px and a quarter-width face at >=27px, both comfortably detectable.
const MAX_ASPECT = 3
const TILE_ASPECT = 6

interface Window {
    left: number
    top: number
    width: number
    height: number
}

function detectionWindows(W: number, H: number): Window[] {
    const long = Math.max(W, H)
    const short = Math.min(W, H)
    if (long / short <= MAX_ASPECT) {
        return [{ left: 0, top: 0, width: W, height: H }]
    }
    const windowLong = TILE_ASPECT * short
    const stride = windowLong - short // overlap of one shortSide: no face can straddle two windows undetected
    const windows: Window[] = []
    for (let pos = 0; ; pos += stride) {
        const start = Math.min(pos, long - windowLong)
        windows.push(
            W >= H
                ? { left: start, top: 0, width: Math.min(windowLong, long), height: H }
                : { left: 0, top: start, width: W, height: Math.min(windowLong, long) }
        )
        if (start + windowLong >= long) {
            break
        }
    }
    return windows
}

async function detectInWindow(
    model: YunetModel,
    src: Src,
    W: number,
    H: number,
    win: Window,
    scoreMin: number
): Promise<{ b: Box; s: number }[]> {
    // The model input is a fixed square, so LETTERBOX: uniform downscale (aspect preserved) into the
    // top-left of a black 640x640 canvas. A fit-to-square squash would smear faces on tall/wide
    // frames past detectability (a 13:1 page compresses faces 13x on one axis); letterboxing keeps
    // them undistorted, merely smaller.
    const scale = YUNET_SIDE / Math.max(win.width, win.height)
    const dw = Math.max(1, Math.round(win.width * scale))
    const dh = Math.max(1, Math.round(win.height * scale))
    const isWholeFrame = win.width === W && win.height === H
    const pipeline = isWholeFrame ? srcSharp(src) : srcSharp(src).extract(win)
    const { data } = await pipeline
        .resize(dw, dh, { fit: 'fill' })
        .extend({ top: 0, left: 0, right: YUNET_SIDE - dw, bottom: YUNET_SIDE - dh, background: '#000' })
        .raw()
        .toBuffer({ resolveWithObject: true })

    // RGB(HWC, 0-255) -> BGR(CHW, float32, no normalization), as OpenCV's YuNet expects.
    const side = YUNET_SIDE
    const chw = new Float32Array(3 * side * side)
    const plane = side * side
    for (let i = 0, p = 0; i < data.length; i += 3, p++) {
        chw[p] = data[i + 2] // B
        chw[plane + p] = data[i + 1] // G
        chw[2 * plane + p] = data[i] // R
    }
    const out = await model.session.run({ [model.inputName]: new ort.Tensor('float32', chw, [1, 3, side, side]) })

    // Uniform inverse scale back to window coords, then offset to frame coords; boxes decoded in the
    // letterbox padding scale past the window edge and get clamped away.
    const sx = win.width / dw
    const sy = win.height / dh
    const cand: { b: Box; s: number }[] = []
    for (const s of STRIDES) {
        const cls = out[`cls_${s}`].data as Float32Array
        const obj = out[`obj_${s}`].data as Float32Array
        const bbox = out[`bbox_${s}`].data as Float32Array
        const fw = Math.floor(side / s)
        const fh = Math.floor(side / s)
        for (let r = 0; r < fh; r++) {
            for (let c = 0; c < fw; c++) {
                const i = r * fw + c
                const score = Math.sqrt(Math.max(0, cls[i]) * Math.max(0, obj[i]))
                if (score < scoreMin) {
                    continue
                }
                const cx = (c + bbox[i * 4]) * s
                const cy = (r + bbox[i * 4 + 1]) * s
                const bw = Math.exp(bbox[i * 4 + 2]) * s
                const bh = Math.exp(bbox[i * 4 + 3]) * s
                const px = bw * PAD
                const py = bh * PAD
                const left = Math.max(0, Math.round((cx - bw / 2 - px) * sx) + win.left)
                const top = Math.max(0, Math.round((cy - bh / 2 - py) * sy) + win.top)
                const right = Math.min(W, Math.round((cx + bw / 2 + px) * sx) + win.left)
                const bottom = Math.min(H, Math.round((cy + bh / 2 + py) * sy) + win.top)
                if (right - left >= 2 && bottom - top >= 2) {
                    cand.push({ b: { left, top, width: right - left, height: bottom - top }, s: score })
                }
            }
        }
    }
    return cand
}

export async function detectFacesYunet(
    model: YunetModel,
    src: Src,
    W: number,
    H: number,
    opts: FaceOpts = {}
): Promise<Box[]> {
    const scoreMin = opts.scoreMin ?? SCORE_MIN
    const cand: { b: Box; s: number }[] = []
    for (const win of detectionWindows(W, H)) {
        cand.push(...(await detectInWindow(model, src, W, H, win, scoreMin)))
    }

    // greedy NMS over all windows (overlap regions produce duplicates for the same face)
    cand.sort((a, b) => b.s - a.s)
    const keep: Box[] = []
    for (const { b } of cand) {
        if (!keep.some((k) => iou(k, b) > NMS_IOU)) {
            keep.push(b)
        }
    }
    return keep
}
