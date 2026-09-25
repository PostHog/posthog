/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Text detector comparison: what each candidate costs, and which words its redaction covers, on the
 * frames the production plan hands the text stage.
 *
 * Setup, once:
 *   npm run setup                              # the production model, which the prod entry uses
 *   tsx dev/text-det-setup.ts                  # candidate models + labelled public images
 *   tsx dev/text-det-corpus.ts                 # synthetic web images with exact boxes
 *   tsx dev/text-det-corpus.ts --calibration   # a disjoint synthetic set, for int8 calibration only
 *   dev/text-det-dynamic-hw.py                 # each docTR model, see its docstring
 *   tsx dev/text-det-bench.ts --dump-calibration "<detector>", then dev/text-det-quantize.py   # int8
 *
 * Runs:
 *   ORT_THREADS=1 tsx dev/text-det-bench.ts [--detectors a,b] [--sets a,b] [--points a,b] [--limit N] [--label name] [--no-kleidiai]
 *   ORT_THREADS=1 tsx dev/text-det-bench.ts --latency [--reps N]
 *
 * ORT_THREADS=1 matches the default in src/cores.ts, which runs one worker per core and gives each
 * worker one intra-op thread.
 *
 * Every candidate runs through the production pre-processing (resize, grey stride padding, the
 * conditional sharpen), the production post-processing (threshold, horizontal dilation, connected
 * components, padding) and the production fill margins. Only the channel order, normalization and
 * thresholds follow each model's own documentation. The baseline entry is checked box for box against
 * src/dbnet.ts on every image, so the harness cannot drift from what production does.
 *
 * A ground-truth word counts as redacted when the fills cover at least 90% of its box. Words are
 * bucketed by their height at the model input, which is the unit the detection floor in src/floors.ts
 * is stated in, so the sweep gives each candidate's floor on real images. "Readable" words are the
 * ones whose ink in the stored image is at least as tall as TEXT_FLOOR.readableAt font px: those are
 * the only words whose miss leaks anything.
 *
 * Operating points:
 *   prod           the canvas src/scale-plan.ts gives the text detector
 *   fitted-global  the smallest canvas that keeps the plan's rule, where every detector sees its
 *                  subject at least the binding ratio (faces) times the safety factor larger than the
 *                  stored image keeps it, for the stored size the plan chose; never above prod
 *   fitted         the same, with text held only to its own floor ratio (TEXT_FLOOR)
 *   tN             the frame scaled by N, for the recall-against-size sweep
 *
 * --latency repeats the prod and both fitted points per image and reports medians, once with ORT's
 * KleidiAI kernels and once without. On an SME-capable Mac those kernels run fp32 convolutions on the
 * matrix unit, which Graviton does not have, so the numbers without them are the closer proxy.
 */
import { existsSync } from 'node:fs'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import * as ort from 'onnxruntime-node'

import { detectTextDbnet, loadDbnet } from '../src/dbnet.ts'
import { numFromEnv } from '../src/env.ts'
import { TEXT_FLOOR, bindingRatio, requiredRatio } from '../src/floors.ts'
import { type Box } from '../src/geometry.ts'
import { type Dims, fitToCanvas, limitsFromEnv, planScales } from '../src/scale-plan.ts'
import { type Src, decodeSrc, probeDims, srcSharp } from '../src/src-image.ts'
import { type GtImage } from './text-det-setup.ts'

const ROOT = new URL('..', import.meta.url).pathname

interface DetectorSpec {
    name: string
    file: string
    channelOrder: 'rgb' | 'bgr'
    /** In the model's own channel order. */
    mean: [number, number, number]
    std: [number, number, number]
    output: 'probability' | 'logits'
    probThreshold: number
    boxScoreMin: number
}

const IMAGENET = { mean: [0.485, 0.456, 0.406], std: [0.229, 0.224, 0.225] } as const
const DOCTR = { mean: [0.798, 0.785, 0.772], std: [0.264, 0.2749, 0.287] } as const

const PROD_PROB_THRESHOLD = numFromEnv('PROB_T', 0.2, 0.05, 0.9)
const PROD_BOX_SCORE = numFromEnv('BOX_SCORE', 0.4, 0.05, 0.95)
const PPOCRV3_THRESHOLDS = { probThreshold: 0.3, boxScoreMin: 0.5 } as const
const PROD_DETECTOR = 'ppocrv6-tiny (prod)'

// PaddleOCR decodes with OpenCV, so its detectors were trained on BGR with the ImageNet statistics
// applied in that order. The ppocrv3 entry feeds RGB and ppocrv3-bgr feeds BGR, so together they
// measure what the channel order costs that model.
const DETECTORS: DetectorSpec[] = [
    {
        name: PROD_DETECTOR,
        file: 'models/dbnet_det.onnx',
        channelOrder: 'bgr',
        ...copyStats(IMAGENET),
        output: 'probability',
        probThreshold: PROD_PROB_THRESHOLD,
        boxScoreMin: PROD_BOX_SCORE,
    },
    {
        name: 'ppocrv3',
        file: 'models/candidates/ppocrv3_det.onnx',
        channelOrder: 'rgb',
        ...copyStats(IMAGENET),
        output: 'probability',
        ...PPOCRV3_THRESHOLDS,
    },
    {
        name: 'ppocrv3-bgr',
        file: 'models/candidates/ppocrv3_det.onnx',
        channelOrder: 'bgr',
        ...copyStats(IMAGENET),
        output: 'probability',
        ...PPOCRV3_THRESHOLDS,
    },
    {
        name: 'ppocrv3-int8',
        file: 'models/candidates/ppocrv3_det_int8.onnx',
        channelOrder: 'rgb',
        ...copyStats(IMAGENET),
        output: 'probability',
        ...PPOCRV3_THRESHOLDS,
    },
    {
        name: 'ppocrv3-int8-conv',
        file: 'models/candidates/ppocrv3_det_int8_conv.onnx',
        channelOrder: 'rgb',
        ...copyStats(IMAGENET),
        output: 'probability',
        ...PPOCRV3_THRESHOLDS,
    },
    {
        name: 'ppocrv4-mobile',
        file: 'models/candidates/ppocrv4_mobile_det.onnx',
        channelOrder: 'bgr',
        ...copyStats(IMAGENET),
        output: 'probability',
        probThreshold: 0.3,
        boxScoreMin: 0.6,
    },
    {
        name: 'ppocrv5-mobile',
        file: 'models/candidates/ppocrv5_mobile_det.onnx',
        channelOrder: 'bgr',
        ...copyStats(IMAGENET),
        output: 'probability',
        probThreshold: 0.3,
        boxScoreMin: 0.6,
    },
    {
        name: 'ppocrv6-tiny-int8',
        file: 'models/candidates/ppocrv6_tiny_det_int8.onnx',
        channelOrder: 'bgr',
        ...copyStats(IMAGENET),
        output: 'probability',
        probThreshold: 0.2,
        boxScoreMin: 0.4,
    },
    {
        name: 'ppocrv6-small',
        file: 'models/candidates/ppocrv6_small_det.onnx',
        channelOrder: 'bgr',
        ...copyStats(IMAGENET),
        output: 'probability',
        probThreshold: 0.2,
        boxScoreMin: 0.45,
    },
    {
        name: 'doctr-db-mbv3',
        file: 'models/candidates/doctr_db_mobilenet_v3_large_dyn.onnx',
        channelOrder: 'rgb',
        ...copyStats(DOCTR),
        output: 'logits',
        probThreshold: 0.3,
        boxScoreMin: 0.1,
    },
    {
        name: 'doctr-db-mbv3-int8',
        file: 'models/candidates/doctr_db_mobilenet_v3_large_int8_dyn.onnx',
        channelOrder: 'rgb',
        ...copyStats(DOCTR),
        output: 'logits',
        probThreshold: 0.3,
        boxScoreMin: 0.1,
    },
    {
        name: 'doctr-fast-tiny',
        file: 'models/candidates/doctr_fast_tiny_dyn.onnx',
        channelOrder: 'rgb',
        ...copyStats(DOCTR),
        output: 'logits',
        probThreshold: 0.1,
        boxScoreMin: 0.1,
    },
]

function copyStats(stats: { mean: readonly number[]; std: readonly number[] }): Pick<DetectorSpec, 'mean' | 'std'> {
    return { mean: [stats.mean[0], stats.mean[1], stats.mean[2]], std: [stats.std[0], stats.std[1], stats.std[2]] }
}

const MIN_AREA_PX = numFromEnv('MIN_AREA', 16, 1, 1024)
const DILATE_X = numFromEnv('DILATE_X', 6, 0, 64)
const PAD_X = numFromEnv('PAD_X', 0.25, 0, 2)
const PAD_Y = numFromEnv('PAD_Y', 0.3, 0, 2)
const DET_SHARPEN = numFromEnv('DET_SHARPEN', 1, 0, 10)
const DET_SHARPEN_BELOW = numFromEnv('DET_SHARPEN_BELOW', 0.6, 0.05, 1)
const TEXT_MARGIN_FRAC = numFromEnv('TEXT_MARGIN_FRAC', 0.25, 0, 2)
const TEXT_MARGIN_BOTTOM_FRAC = numFromEnv('TEXT_MARGIN_BOTTOM_FRAC', 0.45, 0, 2)
const TEXT_MARGIN_MIN = numFromEnv('TEXT_MARGIN_MIN', 4, 0, 64)

const INK_PER_FONT_PX = 0.72
const READABLE_INK_PX = TEXT_FLOOR.readableAt * INK_PER_FONT_PX
const COVERED = 0.9
const HEIGHT_BUCKETS = [0, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 24, 48]
const SWEEP_SCALES = [0.25, 0.35, 0.5, 0.7, 1]
const SETS = ['synthetic', 'born-digital', 'funsd', 'cord']

interface LoadedDetector {
    spec: DetectorSpec
    session: ort.InferenceSession
    inputName: string
    outputName: string
}

interface TextCanvas {
    content: Dims
    canvas: Dims
}

interface Detection {
    boxes: Box[]
    preMs: number
    inferMs: number
    postMs: number
}

async function loadDetector(spec: DetectorSpec, kleidiai: boolean): Promise<LoadedDetector> {
    const session = await ort.InferenceSession.create(join(ROOT, spec.file), {
        graphOptimizationLevel: 'all',
        intraOpNumThreads: numFromEnv('ORT_THREADS', 1, 1, 32),
        interOpNumThreads: 1,
        executionMode: 'sequential',
        enableCpuMemArena: false,
        extra: kleidiai ? {} : { 'mlas.disable_kleidiai': '1' },
    })
    return { spec, session, inputName: session.inputNames[0], outputName: session.outputNames[0] }
}

/** A copy of src/dbnet.ts's preprocess. The baseline check fails when the two drift apart. */
async function preprocess(
    spec: DetectorSpec,
    src: Src,
    text: TextCanvas
): Promise<{ data: Float32Array; rw: number; rh: number; sx: number; sy: number }> {
    const { width: cw, height: ch } = text.content
    const { width: rw, height: rh } = text.canvas
    const totalRatio = Math.sqrt((cw * ch) / src.inputPixels)
    const pipeline = srcSharp(src)
        .resize(cw, ch, { fit: 'fill' })
        .extend({ right: rw - cw, bottom: rh - ch, background: '#808080' })
    const sharpened = DET_SHARPEN > 0 && totalRatio < DET_SHARPEN_BELOW
    const { data } = await (sharpened ? pipeline.sharpen({ sigma: DET_SHARPEN }) : pipeline)
        .raw()
        .toBuffer({ resolveWithObject: true })
    const chw = new Float32Array(3 * rw * rh)
    const plane = rw * rh
    const [m0, m1, m2] = spec.mean
    const [s0, s1, s2] = spec.std
    const first = spec.channelOrder === 'rgb' ? 0 : 2
    const last = 2 - first
    for (let i = 0, p = 0; i < data.length; i += 3, p++) {
        chw[p] = (data[i + first] / 255 - m0) / s0
        chw[plane + p] = (data[i + 1] / 255 - m1) / s1
        chw[2 * plane + p] = (data[i + last] / 255 - m2) / s2
    }
    return { data: chw, rw, rh, sx: src.W / cw, sy: src.H / ch }
}

/** A copy of src/dbnet.ts's postprocess. The baseline check fails when the two drift apart. */
function postprocess(
    spec: DetectorSpec,
    raw: Float32Array,
    rw: number,
    rh: number,
    sx: number,
    sy: number,
    W: number,
    H: number
): Box[] {
    const logits = spec.output === 'logits'
    const rawThreshold = logits ? Math.log(spec.probThreshold / (1 - spec.probThreshold)) : spec.probThreshold
    const prob = (v: number): number => (logits ? 1 / (1 + Math.exp(-v)) : v)
    const bin = new Uint8Array(rw * rh)
    for (let i = 0; i < raw.length; i++) {
        bin[i] = raw[i] >= rawThreshold ? 1 : 0
    }
    const dil = dilateHoriz(bin, rw, rh, DILATE_X)
    const seen = new Uint8Array(rw * rh)
    const stack: number[] = []
    const boxes: Box[] = []
    for (let start = 0; start < dil.length; start++) {
        if (!dil[start] || seen[start]) {
            continue
        }
        let minX = rw
        let minY = rh
        let maxX = 0
        let maxY = 0
        let coreSum = 0
        let coreCnt = 0
        stack.push(start)
        seen[start] = 1
        while (stack.length) {
            const idx = stack.pop()!
            const x = idx % rw
            const y = (idx - x) / rw
            if (bin[idx]) {
                coreSum += prob(raw[idx])
                coreCnt++
            }
            minX = Math.min(minX, x)
            maxX = Math.max(maxX, x)
            minY = Math.min(minY, y)
            maxY = Math.max(maxY, y)
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
        if (coreCnt < MIN_AREA_PX || coreSum / coreCnt < spec.boxScoreMin) {
            continue
        }
        const ex = (maxX - minX + 1) * PAD_X
        const ey = (maxY - minY + 1) * PAD_Y
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

async function detect(det: LoadedDetector, src: Src, text: TextCanvas): Promise<Detection> {
    const t0 = performance.now()
    const { data, rw, rh, sx, sy } = await preprocess(det.spec, src, text)
    const t1 = performance.now()
    const out = await det.session.run({ [det.inputName]: new ort.Tensor('float32', data, [1, 3, rh, rw]) })
    const t2 = performance.now()
    const output = out[det.outputName]
    if (output.dims[2] !== rh || output.dims[3] !== rw) {
        throw new Error(`${det.spec.name}: output ${output.dims.join('x')} for input ${rh}x${rw}`)
    }
    const boxes = postprocess(det.spec, output.data as Float32Array, rw, rh, sx, sy, src.W, src.H)
    return { boxes, preMs: t1 - t0, inferMs: t2 - t1, postMs: performance.now() - t2 }
}

/** A copy of the text margins in src/scrub.ts, which no check compares against. */
function fillBox(t: Box, W: number, H: number): Box | null {
    const mg = Math.round(Math.max(TEXT_MARGIN_MIN, t.height * TEXT_MARGIN_FRAC))
    const mb = Math.round(Math.max(TEXT_MARGIN_MIN, t.height * TEXT_MARGIN_BOTTOM_FRAC))
    const left = Math.max(0, Math.min(W - 1, t.left - mg))
    const top = Math.max(0, Math.min(H - 1, t.top - mg))
    const width = Math.max(1, Math.min(W - left, t.width + 2 * mg))
    const height = Math.max(1, Math.min(H - top, t.height + mg + mb))
    return width < 2 || height < 2 ? null : { left, top, width, height }
}

function coverageTable(boxes: Box[], W: number, H: number): { table: Int32Array; filled: number } {
    const mask = new Uint8Array(W * H)
    for (const b of boxes) {
        for (let y = b.top; y < b.top + b.height; y++) {
            mask.fill(1, y * W + b.left, y * W + b.left + b.width)
        }
    }
    const table = new Int32Array((W + 1) * (H + 1))
    let filled = 0
    for (let y = 0; y < H; y++) {
        let rowSum = 0
        for (let x = 0; x < W; x++) {
            rowSum += mask[y * W + x]
            table[(y + 1) * (W + 1) + x + 1] = table[y * (W + 1) + x + 1] + rowSum
        }
        filled += rowSum
    }
    return { table, filled }
}

function covered(table: Int32Array, W: number, x0: number, y0: number, x1: number, y1: number): number {
    const at = (x: number, y: number): number => table[y * (W + 1) + x]
    return at(x1, y1) - at(x0, y1) - at(x1, y0) + at(x0, y0)
}

interface WordResult {
    set: string
    detector: string
    point: string
    heightAtModel: number
    readable: boolean
    coverage: number
}

interface RunResult {
    set: string
    image: string
    detector: string
    point: string
    canvasPixels: number
    preMs: number
    inferMs: number
    postMs: number
    boxes: number
    fillFraction: number
}

interface ImagePlan {
    set: string
    gt: GtImage
    src: Src
    points: Map<string, TextCanvas>
    storedOverSource: { x: number; y: number }
    contentOverSource: Map<string, number>
    prodText: TextCanvas
}

async function planImage(set: string, gt: GtImage, wanted: string[]): Promise<ImagePlan> {
    const buf = await readFile(join(ROOT, 'test-data/text-det', set, gt.file))
    const limits = limitsFromEnv()
    const source = await probeDims(buf)
    const plan = planScales(source, limits)
    const src = await decodeSrc(buf, plan.frame)
    const frame = plan.frame
    const framePixels = frame.width * frame.height
    // The ratio rule is per axis in pixels: text h px tall in the frame is h * content/frame at the model
    // and h * stored/frame in the artifact, so the content needs ratio * stored on each axis and no more.
    const fittedTo = (ratio: number): TextCanvas => {
        const width = Math.min(plan.text.content.width, Math.ceil(ratio * plan.stored.width))
        const height = Math.min(plan.text.content.height, Math.ceil(ratio * plan.stored.height))
        return {
            content: { width, height },
            canvas: { width: upToStride(width, limits.stride), height: upToStride(height, limits.stride) },
        }
    }
    const points = new Map<string, TextCanvas>()
    const add = (name: string, text: TextCanvas): void => {
        if (wanted.includes(name) || wanted.includes(name.replace(/\d.*$/, 'N'))) {
            points.set(name, text)
        }
    }
    add('prod', plan.text)
    add('fitted-global', fittedTo(bindingRatio() * limits.safetyFactor))
    add('fitted', fittedTo(requiredRatio(TEXT_FLOOR) * limits.safetyFactor))
    for (const s of SWEEP_SCALES) {
        add(`t${s}`, fitToCanvas(frame, Math.max(1, s ** 2 * framePixels), limits.stride))
    }
    const contentOverSource = new Map([...points].map(([name, text]) => [name, text.content.height / source.height]))
    return {
        set,
        gt,
        src,
        points,
        storedOverSource: { x: plan.stored.width / source.width, y: plan.stored.height / source.height },
        contentOverSource,
        prodText: plan.text,
    }
}

const upToStride = (n: number, stride: number): number => Math.max(stride, Math.ceil(n / stride) * stride)

function scoreWords(
    image: ImagePlan,
    detector: string,
    point: string,
    fills: Box[]
): { words: WordResult[]; filled: number } {
    const { W, H } = image.src
    const { table, filled } = coverageTable(fills, W, H)
    const fx = W / image.gt.width
    const fy = H / image.gt.height
    const words: WordResult[] = []
    for (const w of image.gt.words) {
        const [bx0, by0, bx1, by1] = w.box
        const shrinkX = Math.min(image.gt.tolerancePx, (bx1 - bx0) / 3)
        const shrinkY = Math.min(image.gt.tolerancePx, (by1 - by0) / 3)
        const x0 = Math.max(0, Math.floor((bx0 + shrinkX) * fx))
        const y0 = Math.max(0, Math.floor((by0 + shrinkY) * fy))
        const x1 = Math.min(W, Math.ceil((bx1 - shrinkX) * fx))
        const y1 = Math.min(H, Math.ceil((by1 - shrinkY) * fy))
        if (x1 <= x0 || y1 <= y0) {
            continue
        }
        const height = by1 - by0
        words.push({
            set: image.set,
            detector,
            point,
            heightAtModel: height * image.contentOverSource.get(point)!,
            readable: height * image.storedOverSource.y >= READABLE_INK_PX,
            coverage: covered(table, W, x0, y0, x1, y1) / ((x1 - x0) * (y1 - y0)),
        })
    }
    return { words, filled }
}

async function loadSets(sets: string[], limit: number): Promise<{ set: string; gt: GtImage }[]> {
    const out: { set: string; gt: GtImage }[] = []
    for (const set of sets) {
        const path = join(ROOT, 'test-data/text-det', set, 'gt.json')
        if (!existsSync(path)) {
            console.warn(`  skipping ${set}: no ${path} (run dev/text-det-setup.ts / dev/text-det-corpus.ts)`)
            continue
        }
        const images = JSON.parse(await readFile(path, 'utf8')) as GtImage[]
        out.push(...images.slice(0, limit).map((gt) => ({ set, gt })))
    }
    if (out.length === 0) {
        throw new Error(`no images in ${sets.join(', ')}: run the setup commands at the top of this file first`)
    }
    return out
}

function arg(name: string): string | undefined {
    const i = process.argv.indexOf(`--${name}`)
    return i >= 0 ? process.argv[i + 1] : undefined
}

const pct = (n: number, d: number): string => (d ? `${((100 * n) / d).toFixed(1)}%` : '-')
const mean = (xs: number[]): number => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0)
const median = (xs: number[]): number => {
    const s = [...xs].sort((a, b) => a - b)
    return s.length ? s[Math.floor(s.length / 2)] : 0
}

function availableDetectors(names: string[] | undefined): DetectorSpec[] {
    return DETECTORS.filter((d) => (names ? names.includes(d.name) : true)).filter((d) => {
        const ok = existsSync(join(ROOT, d.file))
        if (!ok) {
            console.warn(`  skipping ${d.name}: no ${d.file}`)
        }
        return ok
    })
}

async function quality(): Promise<void> {
    const specs = availableDetectors(arg('detectors')?.split(','))
    const sets = arg('sets')?.split(',') ?? SETS
    const points = arg('points')?.split(',') ?? ['prod', 'fitted-global', 'fitted', 'tN']
    const limit = Number(arg('limit') ?? 1e9)
    const images = await loadSets(sets, limit)
    const detectors = await Promise.all(specs.map((s) => loadDetector(s, !process.argv.includes('--no-kleidiai'))))
    const baselineDetector = detectors.find((d) => d.spec.name === PROD_DETECTOR)
    const baseline = baselineDetector
        ? { detector: baselineDetector, prodModel: await loadDbnet(join(ROOT, baselineDetector.spec.file)) }
        : null
    console.log(`${images.length} images, detectors: ${specs.map((s) => s.name).join(', ')}\n`)

    const words: WordResult[] = []
    const runs: RunResult[] = []
    let mismatches = 0
    let warmed = false
    for (const [n, { set, gt }] of images.entries()) {
        const image = await planImage(set, gt, points)
        if (!warmed) {
            for (const det of detectors) {
                await detect(det, image.src, image.prodText)
            }
            warmed = true
        }
        if (baseline) {
            const ours = await detect(baseline.detector, image.src, image.prodText)
            const theirs = await detectTextDbnet(baseline.prodModel, image.src, image.prodText)
            if (JSON.stringify(ours.boxes) !== JSON.stringify(theirs)) {
                mismatches++
            }
        }
        for (const det of detectors) {
            for (const [point, text] of image.points) {
                const d = await detect(det, image.src, text)
                const fills = d.boxes
                    .map((b) => fillBox(b, image.src.W, image.src.H))
                    .filter((b): b is Box => b !== null)
                const scored = scoreWords(image, det.spec.name, point, fills)
                words.push(...scored.words)
                runs.push({
                    set,
                    image: gt.file,
                    detector: det.spec.name,
                    point,
                    canvasPixels: text.canvas.width * text.canvas.height,
                    preMs: d.preMs,
                    inferMs: d.inferMs,
                    postMs: d.postMs,
                    boxes: d.boxes.length,
                    fillFraction: scored.filled / (image.src.W * image.src.H),
                })
            }
        }
        if ((n + 1) % 25 === 0) {
            console.error(`  ${n + 1}/${images.length}`)
        }
    }
    if (baseline) {
        console.log(`baseline check against src/dbnet.ts: ${mismatches} of ${images.length} images differ\n`)
        if (mismatches) {
            process.exitCode = 1
        }
    }

    const label = arg('label') ?? new Date().toISOString().replace(/[:.]/g, '-')
    await mkdir(join(ROOT, 'out/text-det-bench'), { recursive: true })
    await writeFile(join(ROOT, `out/text-det-bench/${label}.json`), JSON.stringify({ words, runs }))
    report(words, runs, [...new Set(runs.map((r) => r.point))], [...new Set(runs.map((r) => r.set))])
}

function report(words: WordResult[], runs: RunResult[], points: string[], sets: string[]): void {
    const detectors = [...new Set(runs.map((r) => r.detector))]
    for (const point of points.filter((p) => !p.startsWith('t'))) {
        console.log(`=== ${point}: per image means, single-threaded`)
        console.log(
            `  ${'detector'.padEnd(20)}${'canvas MP'.padStart(10)}${'pre ms'.padStart(8)}${'infer ms'.padStart(10)}${'post ms'.padStart(9)}${'total'.padStart(8)}` +
                `${'readable'.padStart(10)}${'read.99'.padStart(9)}${'all words'.padStart(11)}${'filled'.padStart(8)}`
        )
        for (const detector of detectors) {
            const r = runs.filter((x) => x.detector === detector && x.point === point)
            const w = words.filter((x) => x.detector === detector && x.point === point)
            const readable = w.filter((x) => x.readable)
            console.log(
                `  ${detector.padEnd(20)}${(mean(r.map((x) => x.canvasPixels)) / 1e6).toFixed(3).padStart(10)}` +
                    `${mean(r.map((x) => x.preMs))
                        .toFixed(1)
                        .padStart(8)}${mean(r.map((x) => x.inferMs))
                        .toFixed(1)
                        .padStart(10)}` +
                    `${mean(r.map((x) => x.postMs))
                        .toFixed(1)
                        .padStart(9)}${mean(r.map((x) => x.preMs + x.inferMs + x.postMs))
                        .toFixed(1)
                        .padStart(8)}` +
                    `${pct(readable.filter((x) => x.coverage >= COVERED).length, readable.length).padStart(10)}` +
                    `${pct(readable.filter((x) => x.coverage >= 0.99).length, readable.length).padStart(9)}` +
                    `${pct(w.filter((x) => x.coverage >= COVERED).length, w.length).padStart(11)}` +
                    `${pct(mean(r.map((x) => x.fillFraction)), 1).padStart(8)}`
            )
        }
        console.log(
            `  readable words: ${words.filter((x) => x.point === point && x.readable && x.detector === detectors[0]).length}`
        )
        for (const set of sets) {
            const cells = detectors.map((detector) => {
                const readable = words.filter(
                    (x) => x.detector === detector && x.point === point && x.set === set && x.readable
                )
                return pct(readable.filter((x) => x.coverage >= COVERED).length, readable.length).padStart(9)
            })
            console.log(`  readable recall, ${set.padEnd(14)}${cells.join('')}`)
        }
        console.log()
    }

    console.log(`=== recall (coverage >= ${COVERED}) by word height at the model input, all sweep points pooled`)
    const sweep = words.filter((x) => x.point.startsWith('t'))
    const header = HEIGHT_BUCKETS.map((lo, i) => `${lo}-${HEIGHT_BUCKETS[i + 1] ?? ''}`.padStart(8)).join('')
    for (const set of ['all', ...sets]) {
        console.log(`  ${set}`)
        console.log(`    ${'detector'.padEnd(20)}${header}`)
        for (const detector of detectors) {
            const cells = HEIGHT_BUCKETS.map((lo, i) => {
                const hi = HEIGHT_BUCKETS[i + 1] ?? Infinity
                const b = sweep.filter(
                    (x) =>
                        x.detector === detector &&
                        (set === 'all' || x.set === set) &&
                        x.heightAtModel >= lo &&
                        x.heightAtModel < hi
                )
                return (b.length >= 20 ? pct(b.filter((x) => x.coverage >= COVERED).length, b.length) : '.').padStart(8)
            })
            console.log(`    ${detector.padEnd(20)}${cells.join('')}`)
        }
    }
    console.log()
    console.log('=== cost against canvas size, sweep points (ms per image, infer only / total)')
    for (const detector of detectors) {
        const cells = SWEEP_SCALES.map((s) => {
            const r = runs.filter((x) => x.detector === detector && x.point === `t${s}`)
            return r.length
                ? `${mean(r.map((x) => x.inferMs)).toFixed(1)}/${mean(r.map((x) => x.preMs + x.inferMs + x.postMs)).toFixed(1)}`.padStart(
                      13
                  )
                : ''.padStart(13)
        })
        console.log(`  ${detector.padEnd(20)}${cells.join('')}`)
    }
    console.log(`  ${''.padEnd(20)}${SWEEP_SCALES.map((s) => `t${s}`.padStart(13)).join('')}`)
}

async function latency(): Promise<void> {
    const specs = availableDetectors(arg('detectors')?.split(','))
    const reps = Number(arg('reps') ?? 5)
    const limit = Number(arg('limit') ?? 12)
    const points = ['prod', 'fitted-global', 'fitted']
    const images = await loadSets(arg('sets')?.split(',') ?? SETS, limit)
    const plans = await Promise.all(images.map(({ set, gt }) => planImage(set, gt, points)))
    console.log(`${plans.length} images x ${reps} reps, medians per image, then mean over images (ms: infer / total)\n`)
    console.log(`  ${'detector'.padEnd(20)}${'kleidiai'.padStart(9)}${points.map((p) => p.padStart(16)).join('')}`)
    for (const spec of specs) {
        for (const kleidiai of [true, false]) {
            const det = await loadDetector(spec, kleidiai)
            await detect(det, plans[0].src, plans[0].prodText)
            const cells: string[] = []
            for (const point of points) {
                const infer: number[] = []
                const total: number[] = []
                for (const p of plans) {
                    const text = p.points.get(point)!
                    const samples: Detection[] = []
                    for (let r = 0; r < reps; r++) {
                        samples.push(await detect(det, p.src, text))
                    }
                    infer.push(median(samples.map((s) => s.inferMs)))
                    total.push(median(samples.map((s) => s.preMs + s.inferMs + s.postMs)))
                }
                cells.push(`${mean(infer).toFixed(1)} / ${mean(total).toFixed(1)}`.padStart(16))
            }
            console.log(`  ${spec.name.padEnd(20)}${(kleidiai ? 'on' : 'off').padStart(9)}${cells.join('')}`)
            await det.session.release()
        }
    }
}

/** Raw float32 tensors plus index.json, the format dev/text-det-quantize.py reads. */
async function dumpCalibration(detectorName: string): Promise<void> {
    const spec = DETECTORS.find((d) => d.name === detectorName)
    if (!spec) {
        throw new Error(`unknown detector ${detectorName}`)
    }
    const dir = join(ROOT, 'out/text-det-calibration', detectorName.replace(/\W+/g, '_'))
    await mkdir(dir, { recursive: true })
    const images = await loadSets(['calibration'], Number(arg('limit') ?? 1e9))
    const index: { file: string; shape: number[] }[] = []
    for (const { set, gt } of images) {
        const image = await planImage(set, gt, ['prod', 'fitted'])
        for (const [point, text] of image.points) {
            const { data, rw, rh } = await preprocess(spec, image.src, text)
            const file = `${gt.file.replace(/\.\w+$/, '')}_${point}.bin`
            await writeFile(join(dir, file), Buffer.from(data.buffer, data.byteOffset, data.byteLength))
            index.push({ file, shape: [1, 3, rh, rw] })
        }
    }
    await writeFile(join(dir, 'index.json'), JSON.stringify(index))
    console.log(`${index.length} tensors in ${dir}`)
}

const calibrationTarget = arg('dump-calibration')
;(calibrationTarget
    ? dumpCalibration(calibrationTarget)
    : process.argv.includes('--latency')
      ? latency()
      : quality()
).catch((e) => {
    console.error(e)
    process.exit(1)
})
