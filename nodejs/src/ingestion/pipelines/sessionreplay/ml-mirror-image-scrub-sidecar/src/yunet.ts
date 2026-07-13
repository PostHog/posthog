/**
 * YuNet face detection via onnxruntime-node (native, async). Single multi-scale pass (strides
 * 8/16/32) detects small and large faces at once — no tiling — and runs on ORT's background thread.
 * Replaces blazeface + grid tiling.
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

export async function detectFacesYunet(
    model: YunetModel,
    src: Src,
    W: number,
    H: number,
    opts: FaceOpts = {}
): Promise<Box[]> {
    const scoreMin = opts.scoreMin ?? SCORE_MIN
    // The model input is a fixed square, so LETTERBOX: uniform downscale (aspect preserved) into the
    // top-left of a black 640x640 canvas. A fit-to-square squash would smear faces on tall/wide
    // frames past detectability (a 13:1 page compresses faces 13x on one axis); letterboxing keeps
    // them undistorted, merely smaller.
    const scale = YUNET_SIDE / Math.max(W, H)
    const dw = Math.max(1, Math.round(W * scale))
    const dh = Math.max(1, Math.round(H * scale))
    const { data } = await srcSharp(src)
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

    // Uniform inverse scale; boxes decoded in the padding scale past W/H and get clamped away.
    const sx = W / dw
    const sy = H / dh
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
                const left = Math.max(0, Math.round((cx - bw / 2 - px) * sx))
                const top = Math.max(0, Math.round((cy - bh / 2 - py) * sy))
                const right = Math.min(W, Math.round((cx + bw / 2 + px) * sx))
                const bottom = Math.min(H, Math.round((cy + bh / 2 + py) * sy))
                if (right - left >= 2 && bottom - top >= 2) {
                    cand.push({ b: { left, top, width: right - left, height: bottom - top }, s: score })
                }
            }
        }
    }

    // greedy NMS
    cand.sort((a, b) => b.s - a.s)
    const keep: Box[] = []
    for (const { b } of cand) {
        if (!keep.some((k) => iou(k, b) > NMS_IOU)) {
            keep.push(b)
        }
    }
    return keep
}
