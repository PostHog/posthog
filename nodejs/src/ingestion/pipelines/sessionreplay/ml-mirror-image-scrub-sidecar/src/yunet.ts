/**
 * YuNet face detection via onnxruntime-node (native, async). Single multi-scale pass (strides
 * 8/16/32) detects small and large faces at once — no tiling — and runs on ORT's background thread
 * so it overlaps the synchronous tfjs NSFW classify. Replaces blazeface + grid tiling.
 *
 * Decode follows OpenCV's FaceDetectorYN: score = sqrt(cls*obj), grid-anchor bbox, then greedy NMS.
 */
import * as ort from 'onnxruntime-node'

import { type Box, roundTo32 } from './geometry.ts'
import { type Src, srcSharp } from './src-image.ts'

const YUNET_LONG = Number(process.env.YUNET_LONG ?? 640) // detection long side (mult of 32)
const SCORE_MIN = Number(process.env.YUNET_SCORE ?? 0.7)
const NMS_IOU = 0.3
const STRIDES = [8, 16, 32]
const PAD = 0.25 // expand each detected face box so hairline/chin/ears are covered

export interface YunetModel {
    session: ort.InferenceSession
    inputName: string
}

export async function loadYunet(modelPath: string): Promise<YunetModel> {
    const intraOpNumThreads = Number(process.env.ORT_THREADS ?? 1)
    const session = await ort.InferenceSession.create(modelPath, {
        graphOptimizationLevel: 'all',
        intraOpNumThreads,
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
    // This YuNet build has a fixed square input; feed YUNET_LONG x YUNET_LONG and scale boxes back
    // independently per axis (the aspect distortion doesn't hurt detection).
    const dw = roundTo32(YUNET_LONG)
    const dh = dw
    const { data } = await srcSharp(src).resize(dw, dh, { fit: 'fill' }).raw().toBuffer({ resolveWithObject: true })

    // RGB(HWC, 0-255) -> BGR(CHW, float32, no normalization), as OpenCV's YuNet expects.
    const chw = new Float32Array(3 * dw * dh)
    const plane = dw * dh
    for (let i = 0, p = 0; i < data.length; i += 3, p++) {
        chw[p] = data[i + 2] // B
        chw[plane + p] = data[i + 1] // G
        chw[2 * plane + p] = data[i] // R
    }
    const out = await model.session.run({ [model.inputName]: new ort.Tensor('float32', chw, [1, 3, dh, dw]) })

    const sx = W / dw
    const sy = H / dh
    const cand: { b: Box; s: number }[] = []
    for (const s of STRIDES) {
        const cls = out[`cls_${s}`].data as Float32Array
        const obj = out[`obj_${s}`].data as Float32Array
        const bbox = out[`bbox_${s}`].data as Float32Array
        const fw = Math.floor(dw / s)
        const fh = Math.floor(dh / s)
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
