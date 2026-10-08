/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Face detector comparison: what each YuNet variant costs, and which faces its redaction covers, on
 * the frames the production plan hands the face stage.
 *
 *   tsx dev/face-bench.ts --setup                 # models, WIDER FACE val, portraits, composites
 *   tsx dev/face-bench.ts --dump-calibration      # int8 calibration inputs, in out/face-calibration
 *   uv run --with onnxruntime --with onnx python dev/text-det-quantize.py \
 *       models/yunet.onnx out/face-calibration models/candidates/yunet_2026may_int8.onnx
 *   uv run --with onnxruntime --with onnx python dev/text-det-quantize.py \
 *       models/candidates/yunet_n_dynamic.onnx out/face-calibration models/candidates/yunet_n_dynamic_int8.onnx
 *   ORT_THREADS=1 tsx dev/face-bench.ts [--detectors a,b] [--sets a,b] [--limit N] [--label name]
 *
 * Production reads each frame at min(1, 640 / long side) with the dynamic-shape YuNet export, on a
 * canvas that pads only to the model's stride, which is the scale the plan counts for the face stage.
 * The fixed-shape builds take only a 640x640 input, so their "fixed" entries letterbox: a frame
 * smaller than 640 is enlarged and a 16:9 frame is padded with black to a square, and neither buys
 * anything towards the ratio guarantee.
 *
 * The int8 builds calibrate on WIDER FACE, which is CC BY-NC-ND, and on portrait sets that declare no
 * licence, so they show what int8 would buy and cannot ship.
 *
 * Two sets: a fixed subset of WIDER FACE val (real faces with its own boxes), and composites that
 * paste portrait photos into web-shaped frames at controlled sizes, whose boxes come from the
 * production detector on the full-size portrait. A face counts as redacted when the fills cover 90%
 * of its box. "Readable" faces are at least FACE_FLOOR.readableAt px in the stored image.
 */
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import * as ort from 'onnxruntime-node'
import sharp, { type OverlayOptions } from 'sharp'

import { numFromEnv } from '../src/env.ts'
import { FACE_FLOOR } from '../src/floors.ts'
import { type Box } from '../src/geometry.ts'
import { FACE_INPUT_SIDE, limitsFromEnv, planScales } from '../src/scale-plan.ts'
import { type Src, decodeSrc, probeDims, srcSharp } from '../src/src-image.ts'
import { type YunetModel, detectFacesYunet, detectionWindowsForTest, loadYunet } from '../src/yunet.ts'
import { coverage, mulberry32 } from './bench-common.ts'

const ROOT = new URL('..', import.meta.url).pathname
const DATA = join(ROOT, 'test-data/face-bench')
const UA = 'Mozilla/5.0 posthog-replay-image-scrub'

const ZOO =
    'https://github.com/opencv/opencv_zoo/raw/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet'
const WIDER =
    'https://huggingface.co/datasets/CUHK-CSE/wider_face/resolve/db171f1b7fedf4d3453e81297ff02f9915356d19/data'
const DOWNLOADS: { file: string; url: string; sha256: string }[] = [
    {
        file: 'models/candidates/yunet_2023mar_int8.onnx',
        url: `${ZOO}/face_detection_yunet_2023mar_int8.onnx`,
        sha256: '321aa5a6afabf7ecc46a3d06bfab2b579dc96eb5c3be7edd365fa04502ad9294',
    },
    {
        file: 'models/candidates/yunet_2023mar.onnx',
        url: `${ZOO}/face_detection_yunet_2023mar.onnx`,
        sha256: '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4',
    },
    {
        file: 'models/candidates/yunet_n_dynamic.onnx',
        url: 'https://github.com/ShiqiYu/libfacedetection.train/raw/dca340aa082c71081a68d17db8e58b33a58a914b/onnx/yunet_n_dynamic.onnx',
        sha256: '104ee26c71d5c270ce79a6b3dced91c91013260d29a6bf18f9296c5b8c4c2b12',
    },
    // WIDER FACE is CC BY-NC-ND 4.0: an internal eval only, and nothing derived from it is committed.
    {
        file: 'test-data/face-bench/wider/wider_face_split.zip',
        url: `${WIDER}/wider_face_split.zip`,
        sha256: 'c7561e4f5e7a118c249e0a5c5c902b0de90bbf120d7da9fa28d99041f68a8a5c',
    },
    {
        file: 'test-data/face-bench/wider/WIDER_val.zip',
        url: `${WIDER}/WIDER_val.zip`,
        sha256: 'f9efbd09f28c5d2d884be8c0eaef3967158c866a593fc36ab0413e4b2a58a17a',
    },
]
const PORTRAITS: { dataset: string; count: number }[] = [
    { dataset: 'tonyassi/celebrity-1000', count: 50 },
    { dataset: 'logasja/lfw', count: 30 },
]
const WIDER_EVAL_EVERY = 10

interface GtFace {
    box: [number, number, number, number]
}
interface GtImage {
    file: string
    width: number
    height: number
    faces: GtFace[]
}

interface DetectorSpec {
    name: string
    file: string
    /** native: production's input, the frame at min(1, 640/long), stride-padded. fixed: the 640x640 letterbox. */
    input: 'fixed' | 'native'
}

const DETECTORS: DetectorSpec[] = [
    { name: 'yunet (prod)', file: 'models/yunet.onnx', input: 'native' },
    { name: 'yunet fixed', file: 'models/yunet.onnx', input: 'fixed' },
    { name: 'yunet-int8 native', file: 'models/candidates/yunet_2026may_int8.onnx', input: 'native' },
    { name: 'yunet-2023mar fixed', file: 'models/candidates/yunet_2023mar.onnx', input: 'fixed' },
    { name: 'yunet-2023mar-int8 fixed', file: 'models/candidates/yunet_2023mar_int8.onnx', input: 'fixed' },
    // YuNet-n is the larger of the two released YuNet sizes; production and the 2026 export are YuNet-s.
    { name: 'yunet-n native', file: 'models/candidates/yunet_n_dynamic.onnx', input: 'native' },
    { name: 'yunet-n-int8 native', file: 'models/candidates/yunet_n_dynamic_int8.onnx', input: 'native' },
]

const FIXED_SIDE = 640
const STRIDE = 32
const SCORE_MIN = numFromEnv('YUNET_SCORE', 0.7, 0.05, 0.95)
const NMS_IOU = 0.3
const PAD = 0.25
const COVERED = 0.9

async function getBuf(url: string): Promise<Buffer> {
    for (let i = 0; ; i++) {
        try {
            const res = await fetch(url, { signal: AbortSignal.timeout(300000), headers: { 'user-agent': UA } })
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`)
            }
            return Buffer.from(await res.arrayBuffer())
        } catch (e) {
            if (i >= 2) {
                throw e
            }
        }
    }
}

const sha256 = (buf: Buffer): string => createHash('sha256').update(buf).digest('hex')

async function setup(): Promise<void> {
    for (const d of DOWNLOADS) {
        const path = join(ROOT, d.file)
        if (existsSync(path) && sha256(readFileSync(path)) === d.sha256) {
            continue
        }
        await mkdir(join(path, '..'), { recursive: true })
        const buf = await getBuf(d.url)
        if (sha256(buf) !== d.sha256) {
            throw new Error(`${d.file}: sha256 does not match the pin`)
        }
        await writeFile(path, buf)
        console.log(`  ${d.file} (${(buf.length / 1e6).toFixed(1)} MB)`)
    }
    const wider = join(DATA, 'wider')
    if (!existsSync(join(wider, 'WIDER_val'))) {
        execFileSync('unzip', ['-q', '-o', 'wider_face_split.zip'], { cwd: wider })
        execFileSync('unzip', ['-q', '-o', 'WIDER_val.zip'], { cwd: wider })
    }
    await writeWiderSubset()
    await downloadPortraits()
    await writeComposites()
}

/** Every WIDER_EVAL_EVERY-th val image for the eval, and the ones halfway between for calibration. */
async function writeWiderSubset(): Promise<void> {
    const lines = (await readFile(join(DATA, 'wider/wider_face_split/wider_face_val_bbx_gt.txt'), 'utf8')).split('\n')
    const images: { file: string; faces: GtFace[] }[] = []
    for (let i = 0; i < lines.length && lines[i].trim(); ) {
        const file = lines[i].trim()
        const count = Number(lines[i + 1])
        const faces: GtFace[] = []
        for (let k = 0; k < Math.max(1, count); k++) {
            const [x, y, w, h, , , , invalid] = lines[i + 2 + k].trim().split(/\s+/).map(Number)
            if (count > 0 && !invalid && w > 0 && h > 0) {
                faces.push({ box: [x, y, x + w, y + h] })
            }
        }
        images.push({ file, faces })
        i += 2 + Math.max(1, count)
    }
    for (const [set, offset] of [
        ['wider', 0],
        ['wider-calibration', WIDER_EVAL_EVERY / 2],
    ] as const) {
        const picked: GtImage[] = []
        for (const [idx, im] of images.entries()) {
            if (idx % WIDER_EVAL_EVERY !== offset) {
                continue
            }
            const path = join(DATA, 'wider/WIDER_val/images', im.file)
            const { width, height } = await sharp(path).metadata()
            picked.push({ file: `wider/WIDER_val/images/${im.file}`, width: width!, height: height!, faces: im.faces })
        }
        await writeFile(join(DATA, `${set}.json`), JSON.stringify(picked))
        console.log(`  ${set}: ${picked.length} images, ${picked.reduce((n, p) => n + p.faces.length, 0)} faces`)
    }
}

async function downloadPortraits(): Promise<void> {
    const dir = join(DATA, 'portraits')
    if (existsSync(dir) && (await readdir(dir)).length >= 60) {
        return
    }
    await mkdir(dir, { recursive: true })
    for (const p of PORTRAITS) {
        const splits = JSON.parse(
            (
                await getBuf(`https://datasets-server.huggingface.co/splits?dataset=${encodeURIComponent(p.dataset)}`)
            ).toString()
        )
        const split = splits.splits[0]
        const page = JSON.parse(
            (
                await getBuf(
                    `https://datasets-server.huggingface.co/rows?dataset=${encodeURIComponent(p.dataset)}&config=${split.config}&split=${split.split}&offset=0&length=${p.count}`
                )
            ).toString()
        )
        for (const [i, r] of page.rows.entries()) {
            const image = Object.values(r.row as Record<string, unknown>).find(
                (v): v is { src: string } => typeof v === 'object' && v !== null && 'src' in v
            )
            if (image) {
                await writeFile(
                    join(dir, `${p.dataset.replace(/\W+/g, '_')}_${i}.jpg`),
                    await sharp(await getBuf(image.src))
                        .jpeg()
                        .toBuffer()
                )
            }
        }
    }
    console.log(`  portraits: ${(await readdir(dir)).length}`)
}

const COMPOSITE_FRAMES = [
    { name: 'desktop', width: 1920, height: 1080 },
    { name: 'laptop', width: 1280, height: 720 },
    { name: 'mobile', width: 1170, height: 2532 },
    { name: 'profile', width: 800, height: 800 },
    { name: 'thumbnail', width: 480, height: 270 },
    { name: 'ad', width: 300, height: 250 },
    { name: 'avatar', width: 400, height: 400 },
    { name: 'story', width: 320, height: 480 },
]

/** Portraits pasted into web-shaped frames with face sizes swept from 12px to most of the frame. */
async function writeComposites(): Promise<void> {
    const prod = await loadYunet(join(ROOT, 'models/yunet.onnx'))
    const dir = join(DATA, 'composites')
    await mkdir(dir, { recursive: true })
    const portraits: { buf: Buffer; face: [number, number, number, number]; width: number; height: number }[] = []
    for (const f of (await readdir(join(DATA, 'portraits'))).sort()) {
        const buf = await readFile(join(DATA, 'portraits', f))
        const src = await decodeSrc(buf, await probeDims(buf))
        const found = await detectFacesYunet(prod, src, src.W, src.H, { scoreMin: 0.9 })
        if (found.length !== 1) {
            continue
        }
        const b = found[0]
        // Undo the detector's PAD so the stored box is the face itself.
        const w = b.width / (1 + 2 * PAD)
        const h = b.height / (1 + 2 * PAD)
        const cx = b.left + b.width / 2
        const cy = b.top + b.height / 2
        portraits.push({ buf, face: [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], width: src.W, height: src.H })
    }
    for (const [set, seeds] of [
        ['composites', [0, 1, 2, 3, 4, 5, 6, 7]],
        ['composites-calibration', [100, 101]],
    ] as const) {
        const images: GtImage[] = []
        for (const frame of COMPOSITE_FRAMES) {
            for (const seed of seeds) {
                const random = mulberry32(seed * 131 + frame.width)
                // Small frames get fewer, larger cells so they also carry faces big enough to stay
                // readable in their stored image; otherwise nothing there tests the no-upscale path.
                const small = Math.min(frame.width, frame.height) < 600
                const cols = small ? (frame.width > frame.height ? 2 : 1) : 3
                const rows = small ? (frame.width > frame.height ? 1 : 2) : frame.height > frame.width ? 4 : 2
                const cellW = Math.floor(frame.width / cols)
                const cellH = Math.floor(frame.height / rows)
                const layers: OverlayOptions[] = []
                const faces: GtFace[] = []
                for (let r = 0; r < rows; r++) {
                    for (let c = 0; c < cols; c++) {
                        const p = portraits[Math.floor(random() * portraits.length)]
                        const faceW = p.face[2] - p.face[0]
                        const maxFace = Math.min(cellW, cellH) * (small ? 0.9 : 0.55)
                        const minFace = small ? 24 : 12
                        const target = Math.exp(Math.log(minFace) + random() * (Math.log(maxFace) - Math.log(minFace)))
                        const scale = target / faceW
                        const pw = Math.max(1, Math.round(p.width * scale))
                        const ph = Math.max(1, Math.round(p.height * scale))
                        const cropW = Math.min(pw, cellW)
                        const cropH = Math.min(ph, cellH)
                        const fx0 = p.face[0] * scale
                        const fy0 = p.face[1] * scale
                        const cropLeft = Math.max(0, Math.min(pw - cropW, Math.round(fx0 + target / 2 - cropW / 2)))
                        const cropTop = Math.max(
                            0,
                            Math.min(ph - cropH, Math.round(fy0 + ((p.face[3] - p.face[1]) * scale) / 2 - cropH / 2))
                        )
                        const piece = await sharp(p.buf)
                            .resize(pw, ph, { fit: 'fill' })
                            .extract({ left: cropLeft, top: cropTop, width: cropW, height: cropH })
                            .toBuffer()
                        const left = c * cellW
                        const top = r * cellH
                        layers.push({ input: piece, left, top })
                        const renderedScaleX = pw / p.width
                        const renderedScaleY = ph / p.height
                        faces.push({
                            box: [
                                Math.round(left + p.face[0] * renderedScaleX - cropLeft),
                                Math.round(top + p.face[1] * renderedScaleY - cropTop),
                                Math.round(left + p.face[2] * renderedScaleX - cropLeft),
                                Math.round(top + p.face[3] * renderedScaleY - cropTop),
                            ],
                        })
                    }
                }
                const file = `composites/${set}_${frame.name}_${seed}.png`
                await sharp({
                    create: { width: frame.width, height: frame.height, channels: 3, background: '#f3f4f6' },
                })
                    .composite(layers)
                    .png()
                    .toFile(join(DATA, file))
                images.push({ file, width: frame.width, height: frame.height, faces })
            }
        }
        await writeFile(join(DATA, `${set}.json`), JSON.stringify(images))
        console.log(`  ${set}: ${images.length} images, ${images.reduce((n, im) => n + im.faces.length, 0)} faces`)
    }
    await prod.session.release()
}

interface Loaded {
    spec: DetectorSpec
    model: YunetModel
}

const upToStride = (n: number): number => Math.max(STRIDE, Math.ceil(n / STRIDE) * STRIDE)

function iou(a: Box, b: Box): number {
    const x1 = Math.max(a.left, b.left)
    const y1 = Math.max(a.top, b.top)
    const x2 = Math.min(a.left + a.width, b.left + b.width)
    const y2 = Math.min(a.top + a.height, b.top + b.height)
    const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1)
    return inter === 0 ? 0 : inter / (a.width * a.height + b.width * b.height - inter)
}

function inputScale(input: DetectorSpec['input'], win: Box): number {
    const long = Math.max(win.width, win.height)
    return input === 'fixed' ? FIXED_SIDE / long : Math.min(1, FACE_INPUT_SIDE / long)
}

// --dump-calibration builds its tensors here too, so that the int8 builds calibrate on the inputs the native variants see.
async function modelInput(
    src: Src,
    win: Box,
    input: DetectorSpec['input']
): Promise<{ chw: Float32Array; dw: number; dh: number; cw: number; ch: number }> {
    const scale = inputScale(input, win)
    const dw = Math.max(1, Math.round(win.width * scale))
    const dh = Math.max(1, Math.round(win.height * scale))
    const cw = input === 'fixed' ? FIXED_SIDE : upToStride(dw)
    const ch = input === 'fixed' ? FIXED_SIDE : upToStride(dh)
    const whole = win.width === src.W && win.height === src.H
    const { data } = await (whole ? srcSharp(src) : srcSharp(src).extract(win))
        .resize(dw, dh, { fit: 'fill' })
        .extend({ top: 0, left: 0, right: cw - dw, bottom: ch - dh, background: '#000' })
        .raw()
        .toBuffer({ resolveWithObject: true })
    const chw = new Float32Array(3 * cw * ch)
    const plane = cw * ch
    for (let i = 0, p = 0; i < data.length; i += 3, p++) {
        chw[p] = data[i + 2]
        chw[plane + p] = data[i + 1]
        chw[2 * plane + p] = data[i]
    }
    return { chw, dw, dh, cw, ch }
}

/** The fixed-shape builds: src/yunet.ts's windows and decode, on the 640x640 letterbox those builds require. */
async function detectFixed(model: YunetModel, src: Src): Promise<Box[]> {
    const { W, H } = src
    const cand: { b: Box; s: number }[] = []
    for (const win of detectionWindowsForTest(W, H)) {
        const { chw, dw, dh, cw, ch } = await modelInput(src, win, 'fixed')
        const out = await model.session.run({ [model.inputName]: new ort.Tensor('float32', chw, [1, 3, ch, cw]) })
        const sx = win.width / dw
        const sy = win.height / dh
        for (const s of [8, 16, 32]) {
            const cls = out[`cls_${s}`].data as Float32Array
            const obj = out[`obj_${s}`].data as Float32Array
            const bbox = out[`bbox_${s}`].data as Float32Array
            const fw = cw / s
            const fh = ch / s
            if (cls.length !== fw * fh) {
                throw new Error(`cls_${s} has ${cls.length} cells for a ${fw}x${fh} grid`)
            }
            for (let r = 0; r < fh; r++) {
                for (let c = 0; c < fw; c++) {
                    const i = r * fw + c
                    const score = Math.sqrt(Math.max(0, cls[i]) * Math.max(0, obj[i]))
                    if (score < SCORE_MIN) {
                        continue
                    }
                    const cx = (c + bbox[i * 4]) * s
                    const cy = (r + bbox[i * 4 + 1]) * s
                    const bw = Math.exp(bbox[i * 4 + 2]) * s
                    const bh = Math.exp(bbox[i * 4 + 3]) * s
                    const left = Math.max(0, Math.round((cx - bw / 2 - bw * PAD) * sx) + win.left)
                    const top = Math.max(0, Math.round((cy - bh / 2 - bh * PAD) * sy) + win.top)
                    const right = Math.min(W, Math.round((cx + bw / 2 + bw * PAD) * sx) + win.left)
                    const bottom = Math.min(H, Math.round((cy + bh / 2 + bh * PAD) * sy) + win.top)
                    if (right - left >= 2 && bottom - top >= 2) {
                        cand.push({ b: { left, top, width: right - left, height: bottom - top }, s: score })
                    }
                }
            }
        }
    }
    cand.sort((a, b) => b.s - a.s)
    const keep: Box[] = []
    for (const { b } of cand) {
        if (!keep.some((k) => iou(k, b) > NMS_IOU)) {
            keep.push(b)
        }
    }
    return keep
}

/** How much the face stage enlarges or shrinks the frame, which is what a face's size at the model depends on. */
function modelScale(spec: DetectorSpec, W: number, H: number): number {
    return inputScale(spec.input, detectionWindowsForTest(W, H)[0])
}

function detect(d: Loaded, src: Src): Promise<Box[]> {
    return d.spec.input === 'native' ? detectFacesYunet(d.model, src, src.W, src.H) : detectFixed(d.model, src)
}

interface FaceResult {
    set: string
    detector: string
    faceAtModel: number
    readable: boolean
    coverage: number
}
interface RunResult {
    set: string
    image: string
    detector: string
    ms: number
    boxes: number
    filledFraction: number
    sourcePixels: number
}

function arg(name: string): string | undefined {
    const i = process.argv.indexOf(`--${name}`)
    return i >= 0 ? process.argv[i + 1] : undefined
}

async function loadSet(set: string, limit: number): Promise<{ set: string; gt: GtImage }[]> {
    const path = join(DATA, `${set}.json`)
    if (!existsSync(path)) {
        console.warn(`  skipping ${set}: run --setup first`)
        return []
    }
    return (JSON.parse(await readFile(path, 'utf8')) as GtImage[]).slice(0, limit).map((gt) => ({ set, gt }))
}

async function loadDetectors(names: string[] | undefined): Promise<Loaded[]> {
    const specs = DETECTORS.filter((d) => (names ? names.includes(d.name) : true)).filter((d) => {
        const ok = existsSync(join(ROOT, d.file))
        if (!ok) {
            console.warn(`  skipping ${d.name}: no ${d.file}`)
        }
        return ok
    })
    return Promise.all(specs.map(async (spec) => ({ spec, model: await loadYunet(join(ROOT, spec.file)) })))
}

async function evaluate(): Promise<void> {
    const limit = Number(arg('limit') ?? 1e9)
    const sets = arg('sets')?.split(',') ?? ['wider', 'composites']
    const images = (await Promise.all(sets.map((s) => loadSet(s, limit)))).flat()
    const detectors = await loadDetectors(arg('detectors')?.split(','))
    console.log(`${images.length} images, detectors: ${detectors.map((d) => d.spec.name).join(', ')}\n`)
    const limits = limitsFromEnv()
    const faces: FaceResult[] = []
    const runs: RunResult[] = []
    let warmed = false
    for (const [n, { set, gt }] of images.entries()) {
        const buf = await readFile(join(DATA, gt.file))
        const plan = planScales({ width: gt.width, height: gt.height }, limits)
        const src = await decodeSrc(buf, plan.frame)
        const fx = src.W / gt.width
        const fy = src.H / gt.height
        const storedOverSource = plan.stored.height / gt.height
        if (!warmed) {
            for (const d of detectors) {
                await detect(d, src)
            }
            warmed = true
        }
        for (const d of detectors) {
            const t0 = performance.now()
            const boxes = await detect(d, src)
            const ms = performance.now() - t0
            let filled = 0
            const mask = new Uint8Array(src.W * src.H)
            for (const b of boxes) {
                for (let y = b.top; y < b.top + b.height; y++) {
                    mask.fill(1, y * src.W + b.left, y * src.W + b.left + b.width)
                }
            }
            for (const v of mask) {
                filled += v
            }
            runs.push({
                set,
                image: gt.file,
                detector: d.spec.name,
                ms,
                boxes: boxes.length,
                filledFraction: filled / (src.W * src.H),
                sourcePixels: gt.width * gt.height,
            })
            const atModel = modelScale(d.spec, src.W, src.H)
            for (const f of gt.faces) {
                const [x0, y0, x1, y1] = f.box
                const side = Math.max(x1 - x0, y1 - y0)
                faces.push({
                    set,
                    detector: d.spec.name,
                    faceAtModel: side * fx * atModel,
                    readable: side * storedOverSource >= FACE_FLOOR.readableAt,
                    coverage: coverage(boxes, [
                        Math.floor(x0 * fx),
                        Math.floor(y0 * fy),
                        Math.ceil(x1 * fx),
                        Math.ceil(y1 * fy),
                    ]),
                })
            }
        }
        if ((n + 1) % 50 === 0) {
            console.error(`  ${n + 1}/${images.length}`)
        }
    }
    const label = arg('label') ?? 'face-bench'
    await mkdir(join(ROOT, 'out/face-bench'), { recursive: true })
    await writeFile(join(ROOT, `out/face-bench/${label}.json`), JSON.stringify({ faces, runs }))
    report(faces, runs, sets)
}

function report(faces: FaceResult[], runs: RunResult[], sets: string[]): void {
    const detectors = [...new Set(runs.map((r) => r.detector))]
    const mean = (xs: number[]): number => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length)
    const pct = (n: number, d: number): string => (d ? `${((100 * n) / d).toFixed(1)}%` : '-')
    console.log(
        `  ${'detector'.padEnd(24)}${'ms/img'.padStart(8)}${'readable'.padStart(10)}${'visible'.padStart(9)}${'all faces'.padStart(11)}${'filled'.padStart(8)}`
    )
    for (const d of detectors) {
        const r = runs.filter((x) => x.detector === d)
        const f = faces.filter((x) => x.detector === d)
        const readable = f.filter((x) => x.readable)
        console.log(
            `  ${d.padEnd(24)}${mean(r.map((x) => x.ms))
                .toFixed(1)
                .padStart(8)}` +
                `${pct(readable.filter((x) => x.coverage >= COVERED).length, readable.length).padStart(10)}` +
                `${String(readable.filter((x) => x.coverage < 0.1).length).padStart(9)}` +
                `${pct(f.filter((x) => x.coverage >= COVERED).length, f.length).padStart(11)}` +
                `${pct(mean(r.map((x) => x.filledFraction)), 1).padStart(8)}`
        )
    }
    for (const set of sets) {
        const n = faces.filter((x) => x.detector === detectors[0] && x.set === set)
        console.log(`  ${set}: ${n.length} faces, ${n.filter((x) => x.readable).length} readable in the stored image`)
    }
    console.log('\n  recall by face size at the model input (px), all sets')
    const edges = [0, 8, 12, 16, 24, 32, 48, 64, 96, 1e9]
    console.log(
        `    ${'detector'.padEnd(24)}${edges
            .slice(0, -1)
            .map((lo, i) => `${lo}-${edges[i + 1] === 1e9 ? '' : edges[i + 1]}`.padStart(8))
            .join('')}`
    )
    for (const d of detectors) {
        const cells = edges.slice(0, -1).map((lo, i) => {
            const b = faces.filter((x) => x.detector === d && x.faceAtModel >= lo && x.faceAtModel < edges[i + 1])
            return (b.length >= 20 ? pct(b.filter((x) => x.coverage >= COVERED).length, b.length) : '.').padStart(8)
        })
        console.log(`    ${d.padEnd(24)}${cells.join('')}`)
    }
}

async function dumpCalibration(): Promise<void> {
    const dir = join(ROOT, 'out/face-calibration')
    await mkdir(dir, { recursive: true })
    const images = [...(await loadSet('wider-calibration', 60)), ...(await loadSet('composites-calibration', 1e9))]
    const limits = limitsFromEnv()
    const index: { file: string; shape: number[] }[] = []
    for (const [n, { gt }] of images.entries()) {
        const buf = await readFile(join(DATA, gt.file))
        const src = await decodeSrc(buf, planScales({ width: gt.width, height: gt.height }, limits).frame)
        const { chw, cw, ch } = await modelInput(src, detectionWindowsForTest(src.W, src.H)[0], 'native')
        const file = `face_${n}.bin`
        await writeFile(join(dir, file), Buffer.from(chw.buffer))
        index.push({ file, shape: [1, 3, ch, cw] })
    }
    await writeFile(join(dir, 'index.json'), JSON.stringify(index))
    console.log(`${index.length} tensors in ${dir}`)
}

;(process.argv.includes('--setup')
    ? setup()
    : process.argv.includes('--dump-calibration')
      ? dumpCalibration()
      : evaluate()
).catch((e) => {
    console.error(e)
    process.exit(1)
})
