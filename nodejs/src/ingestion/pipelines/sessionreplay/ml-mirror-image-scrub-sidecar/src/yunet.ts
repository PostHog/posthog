/**
 * YuNet face detection via onnxruntime-node (native, async). One multi-scale pass (strides 8/16/32)
 * detects small and large faces at once, so normal-aspect frames need a single inference; only
 * extreme-aspect frames are tiled (see detectionWindows).
 *
 * Decode follows OpenCV's FaceDetectorYN: score = sqrt(cls*obj), grid-anchor bbox, then greedy NMS.
 */
import * as ort from 'onnxruntime-node'

import { ORT_THREADS } from './cores.ts'
import { numFromEnv } from './env.ts'
import { type Box } from './geometry.ts'
import { rgbToChw } from './pixel-convert.ts'
// Tiling bounds for extreme-aspect frames, with figures for the default 640 input (a larger input
// scales them up). A single pass scales by 640/longSide, so on a
// very tall/wide image a face (at most ~shortSide across) can land below the detector's smallest
// stride. Above MAX_ASPECT the frame is cut along its long axis into windows of aspect TILE_ASPECT
// (overlapping by one shortSide, so a face — at most one shortSide across — is always fully inside
// some window): each window then scales by 640/(TILE_ASPECT*shortSide), keeping any face at least
// ~640/TILE_ASPECT/(shortSide/faceSize) px. TILE_ASPECT=6 keeps a face spanning the full short side
// at >=107px and a quarter-width face at >=27px, both comfortably detectable.
// Kept in step with PlanLimits.faceTileAbove / faceTileAspect: the planner needs the same rule to
// know how much of a long frame this stage really sees, and two copies of it is the drift the
// planner exists to remove.
import {
    DEFAULT_FACE_INPUT_SIDE,
    FACE_TILE_ABOVE,
    FACE_TILE_ASPECT,
    faceWindowLong,
    limitsFromEnv,
} from './scale-plan.ts'
import { type Src, srcSharp } from './src-image.ts'

const SCORE_MIN = numFromEnv('YUNET_SCORE', 0.7, 0.05, 0.95)
const FACE_INPUT_SIDES = faceInputSides(limitsFromEnv().faceInputSide)

/**
 * The input sizes faces are detected at. YuNet's measured floors come from 640, and a close-up face at a larger input
 * reaches the model bigger than anything it was checked against, so a larger input adds a 640 pass rather than
 * replacing it.
 */
export function faceInputSides(inputSide: number): number[] {
    return inputSide > DEFAULT_FACE_INPUT_SIDE ? [inputSide, DEFAULT_FACE_INPUT_SIDE] : [inputSide]
}
const NMS_IOU = 0.3
const STRIDES = [8, 16, 32]
const LARGEST_STRIDE = 32
const PAD = 0.25 // expand each detected face box so hairline/chin/ears are covered

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
        // The arena allocator holds on to peak allocations for reuse, which on a pool of workers each
        // running their own sessions is memory multiplied by the worker count: measured at 719MB per
        // worker with it on against 570MB off, on a 2 MP frame. It buys no measurable CPU here
        // (97.6% of baseline over the eval corpus, inside run-to-run noise), so the memory is free.
        enableCpuMemArena: false,
    })
    return { session, inputName: session.inputNames[0] }
}

const upToStride = (n: number): number => Math.max(LARGEST_STRIDE, Math.ceil(n / LARGEST_STRIDE) * LARGEST_STRIDE)

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

const MAX_ASPECT = FACE_TILE_ABOVE
const TILE_ASPECT = FACE_TILE_ASPECT

interface Window {
    left: number
    top: number
    width: number
    height: number
}

/** Exposed for tests: a window that starts off the edge silently disables face redaction for a
 *  whole class of frame shapes, and nothing downstream errors when it happens. */
export function detectionWindowsForTest(W: number, H: number): Window[] {
    return detectionWindows(W, H)
}

function detectionWindows(W: number, H: number): Window[] {
    const long = Math.max(W, H)
    const short = Math.min(W, H)
    if (long / short <= MAX_ASPECT) {
        return [{ left: 0, top: 0, width: W, height: H }]
    }
    // Never longer than the frame: for an aspect between MAX_ASPECT and TILE_ASPECT the frame is
    // SHORTER than a full tile, so an unclamped windowLong made `long - windowLong` negative and
    // every window started off the left (or top) edge. Face boxes are translated by that offset, so
    // at an aspect just over MAX_ASPECT the shift approached the whole long side and no box survived
    // the width check: face redaction was silently off for every frame between 3:1 and 6:1.
    // From the planner, so the work done here and the scale the plan assumed cannot disagree, and so
    // the inference count is bounded: it grows with the aspect ratio, which the area budget does not
    // constrain, and an unbounded count is a worker pinned by one small crafted image.
    const windowLong = faceWindowLong(long, short, MAX_ASPECT, TILE_ASPECT)
    const stride = Math.max(1, windowLong - short) // overlap of one shortSide: no face can straddle two windows undetected
    const windows: Window[] = []
    for (let pos = 0; ; pos += stride) {
        const start = Math.max(0, Math.min(pos, long - windowLong))
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

const windowScale = (win: Window, inputSide: number): number => Math.min(1, inputSide / Math.max(win.width, win.height))

/** A window already within the smaller side reaches the model at full size on every pass. */
export function passesForWindow(win: Window, inputSides: number[]): number[] {
    const scales = new Set<number>()
    return inputSides.filter((side) => {
        const scale = windowScale(win, side)
        if (scales.has(scale)) {
            return false
        }
        scales.add(scale)
        return true
    })
}

type Candidate = { b: Box; s: number }

/** Scores from different input sizes are not comparable, so a box from one pass never suppresses another pass's. */
export function mergePasses(passes: Candidate[][]): Box[] {
    return passes.flatMap((cand) => {
        const sorted = [...cand].sort((a, b) => b.s - a.s)
        const keep: Box[] = []
        for (const { b } of sorted) {
            if (!keep.some((k) => iou(k, b) > NMS_IOU)) {
                keep.push(b)
            }
        }
        return keep
    })
}

async function detectInWindow(
    model: YunetModel,
    src: Src,
    W: number,
    H: number,
    win: Window,
    scoreMin: number,
    inputSide: number
): Promise<Candidate[]> {
    // Padding rather than resizing to reach the stride, because resizing up enlarges real pixels (rule 1 in scale-plan.ts).
    const scale = windowScale(win, inputSide)
    const dw = Math.max(1, Math.round(win.width * scale))
    const dh = Math.max(1, Math.round(win.height * scale))
    const cw = upToStride(dw)
    const ch = upToStride(dh)
    const isWholeFrame = win.width === W && win.height === H
    const pipeline = isWholeFrame ? srcSharp(src) : srcSharp(src).extract(win)
    const { data } = await pipeline
        .resize(dw, dh, { fit: 'fill' })
        .extend({ top: 0, left: 0, right: cw - dw, bottom: ch - dh, background: '#000' })
        .raw()
        .toBuffer({ resolveWithObject: true })

    // RGB(HWC, 0-255) -> BGR(CHW, float32, no normalization), as OpenCV's YuNet expects.
    const chw = new Float32Array(3 * cw * ch)
    rgbToChw(data, chw, 'bgr')
    const out = await model.session.run({ [model.inputName]: new ort.Tensor('float32', chw, [1, 3, ch, cw]) })

    // Uniform inverse scale back to window coords, then offset to frame coords; boxes decoded in the
    // padding scale past the window edge and get clamped away.
    const sx = win.width / dw
    const sy = win.height / dh
    const cand: Candidate[] = []
    for (const s of STRIDES) {
        const cls = out[`cls_${s}`].data as Float32Array
        const obj = out[`obj_${s}`].data as Float32Array
        const bbox = out[`bbox_${s}`].data as Float32Array
        const fw = cw / s
        const fh = ch / s
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
    const windows = detectionWindows(W, H)
    const passes: Candidate[][] = FACE_INPUT_SIDES.map(() => [])
    for (const win of windows) {
        for (const inputSide of passesForWindow(win, FACE_INPUT_SIDES)) {
            const pass = passes[FACE_INPUT_SIDES.indexOf(inputSide)]
            pass.push(...(await detectInWindow(model, src, W, H, win, scoreMin, inputSide)))
        }
    }
    return mergePasses(passes)
}
