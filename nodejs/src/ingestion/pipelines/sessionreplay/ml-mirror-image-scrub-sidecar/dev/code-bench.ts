/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Code detector cost against scale: how small the frame handed to zxing can get before a code that
 * is still decodable from the stored image goes unredacted.
 *
 *   tsx dev/code-bench.ts [--limit N] [--label name] [--shard k/n]
 *
 * zxing reads the full frame today. A code only leaks if a reader can decode it from the stored
 * image, and the stored image is several times smaller than the frame, so zxing may not need the
 * whole frame to find every code that could leak. Each generated image is checked twice: zxing on the
 * unredacted stored image (at 1x, 2x and 3x, since an attacker can upscale) decides whether the code
 * could leak, and zxing on the frame at each scale decides whether the scrub would have covered it.
 *
 * Scales are either a fraction of the frame (fN), a multiple of the stored image's scale (sN), or
 * "plan": the multiple the scale plan already requires of every detector (binding ratio times the
 * safety factor). None is ever above the frame. The sN points answer the ratio question directly: the smallest multiple at
 * which every leakable code is still covered is the ratio codes need.
 */
import { readFileSync } from 'node:fs'
import { mkdir, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { join } from 'node:path'
import sharp from 'sharp'
import { prepareZXingModule, writeBarcode } from 'zxing-wasm/writer'

import { bindingRatio } from '../src/floors.ts'
import { detectCodes } from '../src/qr.ts'
import { limitsFromEnv, planScales } from '../src/scale-plan.ts'
import { type Src, decodeSrc } from '../src/src-image.ts'
import { coverage } from './bench-common.ts'

// src-image.ts loads image-input.ts, which blocks the SVG loader for the whole process, and the codes
// are drawn from zxing's SVG output.
sharp.unblock({ operation: ['VipsForeignLoadSvg'] })

const writerWasm = readFileSync(createRequire(`${process.cwd()}/`).resolve('zxing-wasm/writer/zxing_writer.wasm'))
prepareZXingModule({
    overrides: {
        wasmBinary: writerWasm.buffer.slice(writerWasm.byteOffset, writerWasm.byteOffset + writerWasm.byteLength),
    },
})

const ROOT = new URL('..', import.meta.url).pathname

type Format = 'QRCode' | 'DataMatrix' | 'Aztec' | 'PDF417' | 'Code128'

const CODES: { payload: string; format: Format }[] = [
    { payload: 'otpauth://totp/Acme:jane.doe@example.com?secret=JBSWY3DPEHPK3PXP&issuer=Acme', format: 'QRCode' },
    { payload: 'https://acme.example.com/t/b7f3a91c', format: 'QRCode' },
    { payload: 'ACCT-0098761234', format: 'DataMatrix' },
    { payload: 'TICKET-A1B2C3-SEAT-14F', format: 'Aztec' },
    { payload: 'PNR X7Q2LM FLIGHT 0421', format: 'PDF417' },
    { payload: '4242424242424242', format: 'Code128' },
]

const FRAMES: { name: string; width: number; height: number }[] = [
    { name: 'desktop', width: 1920, height: 1080 },
    { name: 'laptop', width: 1280, height: 720 },
    { name: 'mobile', width: 1170, height: 2532 },
    { name: 'product', width: 800, height: 800 },
    { name: 'thumbnail', width: 480, height: 270 },
    { name: 'ad', width: 300, height: 250 },
]

/** Longest code side as a fraction of the frame's short side. */
const CODE_FRACTIONS = [0.06, 0.09, 0.13, 0.18, 0.26, 0.38, 0.55]

const DEGRADATIONS = ['none', 'blur', 'rotate', 'jpeg'] as const
type Degradation = (typeof DEGRADATIONS)[number]

const FRAME_SCALES = [1, 0.7, 0.5, 0.35, 0.25]
const STORED_MULTIPLES = [1, 1.3, 1.6, 2, 3, 4]
const COVERED = 0.9

interface Sample {
    file: string
    frame: { name: string; width: number; height: number }
    code: (typeof CODES)[number]
    fraction: number
    degradation: Degradation
    png: Buffer
    /** Where the code's pixels sit in the source image: [left, top, right, bottom). */
    box: [number, number, number, number]
    /** Modules along the code's long side, including zxing's quiet zone. */
    modules: number
}

async function renderCode(code: (typeof CODES)[number], side: number): Promise<{ png: Buffer; modules: number }> {
    const { svg } = await writeBarcode(code.payload, { format: code.format })
    const meta = await sharp(Buffer.from(svg)).metadata()
    const modules = Math.max(meta.width!, meta.height!)
    const png = await sharp(Buffer.from(svg))
        .resize(side, side, { fit: 'inside', kernel: 'nearest' })
        .flatten({ background: '#ffffff' })
        .png()
        .toBuffer()
    return { png, modules }
}

async function makeSample(
    frame: (typeof FRAMES)[number],
    code: (typeof CODES)[number],
    fraction: number,
    degradation: Degradation,
    n: number
): Promise<Sample | null> {
    const side = Math.round(Math.min(frame.width, frame.height) * fraction)
    let { png, modules } = await renderCode(code, side)
    if (degradation === 'rotate') {
        png = await sharp(png).rotate(8, { background: '#ffffff' }).png().toBuffer()
    }
    const { width: cw, height: ch } = await sharp(png).metadata()
    if (cw! >= frame.width || ch! >= frame.height) {
        return null
    }
    const left = Math.round((frame.width - cw!) * 0.62)
    const top = Math.round((frame.height - ch!) * 0.38)
    const lines = Array.from(
        { length: 6 },
        (_, i) =>
            `<text x="${Math.round(frame.width * 0.05)}" y="${Math.round(frame.height * (0.1 + i * 0.05))}" font-family="Arial" font-size="${Math.max(9, Math.round(frame.height * 0.02))}" fill="#374151">Order #A1B2C3 scan to confirm your booking</text>`
    ).join('')
    const background = Buffer.from(
        `<svg xmlns="http://www.w3.org/2000/svg" width="${frame.width}" height="${frame.height}"><rect width="100%" height="100%" fill="#f3f4f6"/>${lines}</svg>`
    )
    let out = sharp(background).composite([{ input: png, left, top }])
    if (degradation === 'blur') {
        out = sharp(await out.png().toBuffer()).blur(0.9)
    }
    const encoded = degradation === 'jpeg' ? await out.jpeg({ quality: 70 }).toBuffer() : await out.png().toBuffer()
    return {
        file: `code_${frame.name}_${code.format}_${Math.round(fraction * 100)}_${degradation}_${n}`,
        frame,
        code,
        fraction,
        degradation,
        png: encoded,
        box: [left, top, left + cw!, top + ch!],
        modules,
    }
}

async function scaled(src: Src, width: number, height: number): Promise<Src> {
    if (width === src.W && height === src.H) {
        return src
    }
    const { data } = await sharp(src.data, { raw: { width: src.W, height: src.H, channels: 3 } })
        .resize(width, height, { fit: 'fill' })
        .raw()
        .toBuffer({ resolveWithObject: true })
    return { data, W: width, H: height, format: 'raw', inputPixels: src.inputPixels }
}

/** Whether zxing decodes the code from the stored image, as it is or upscaled the way an attacker would. */
async function decodableFromStored(src: Src, stored: { width: number; height: number }): Promise<boolean> {
    const art = await scaled(src, stored.width, stored.height)
    for (const factor of [1, 2, 3]) {
        const probe =
            factor === 1
                ? art
                : await (async (): Promise<Src> => {
                      const { data } = await sharp(art.data, { raw: { width: art.W, height: art.H, channels: 3 } })
                          .resize(art.W * factor, art.H * factor, { kernel: 'cubic' })
                          .raw()
                          .toBuffer({ resolveWithObject: true })
                      return { data, W: art.W * factor, H: art.H * factor, format: 'raw', inputPixels: art.inputPixels }
                  })()
        if ((await detectCodes(probe)).length > 0) {
            return true
        }
    }
    return false
}

interface Result {
    file: string
    frame: string
    format: Format
    degradation: Degradation
    sourcePixels: number
    leakable: boolean
    point: string
    zxingPixels: number
    modulePxAtZxing: number
    ms: number
    coverage: number
}

function arg(name: string): string | undefined {
    const i = process.argv.indexOf(`--${name}`)
    return i >= 0 ? process.argv[i + 1] : undefined
}

async function main(): Promise<void> {
    const limit = Number(arg('limit') ?? 1e9)
    const limits = limitsFromEnv()
    const combinations = FRAMES.flatMap((frame) =>
        CODES.flatMap((code) =>
            CODE_FRACTIONS.flatMap((fraction) =>
                DEGRADATIONS.map((degradation) => ({ frame, code, fraction, degradation }))
            )
        )
    )
    const samples: Sample[] = []
    for (const [seed, { frame, code, fraction, degradation }] of combinations.entries()) {
        if (samples.length >= limit) {
            break
        }
        const s = await makeSample(frame, code, fraction, degradation, seed)
        if (s) {
            samples.push(s)
        }
    }
    console.log(`${samples.length} images`)

    const [shard, shards] = (arg('shard') ?? '0/1').split('/').map(Number)
    const results: Result[] = []
    for (const [i, s] of samples.entries()) {
        if (i % shards !== shard) {
            continue
        }
        const source = { width: s.frame.width, height: s.frame.height }
        const plan = planScales(source, limits)
        const src = await decodeSrc(s.png, plan.frame)
        const leakable = await decodableFromStored(src, plan.stored)
        const fx = src.W / source.width
        const fy = src.H / source.height
        const gt: [number, number, number, number] = [
            Math.floor(s.box[0] * fx),
            Math.floor(s.box[1] * fy),
            Math.ceil(s.box[2] * fx),
            Math.ceil(s.box[3] * fy),
        ]
        const storedScale = Math.max(plan.stored.width / src.W, plan.stored.height / src.H)
        const points: [string, number][] = [
            ...FRAME_SCALES.map((f): [string, number] => [`f${f}`, f]),
            ...STORED_MULTIPLES.map((m): [string, number] => [`s${m}`, Math.min(1, m * storedScale)]),
            ['plan', Math.min(1, bindingRatio() * limits.safetyFactor * storedScale)],
        ]
        for (const [point, scale] of points) {
            const w = Math.max(1, Math.round(src.W * scale))
            const h = Math.max(1, Math.round(src.H * scale))
            const input = await scaled(src, w, h)
            const t0 = performance.now()
            const boxes = await detectCodes(input)
            const ms = performance.now() - t0
            const back = boxes.map((b) => ({
                left: Math.floor((b.left * src.W) / w),
                top: Math.floor((b.top * src.H) / h),
                width: Math.ceil((b.width * src.W) / w),
                height: Math.ceil((b.height * src.H) / h),
            }))
            const codeSideAtZxing = Math.max(s.box[2] - s.box[0], s.box[3] - s.box[1]) * fx * (w / src.W)
            results.push({
                file: s.file,
                frame: s.frame.name,
                format: s.code.format,
                degradation: s.degradation,
                sourcePixels: source.width * source.height,
                leakable,
                point,
                zxingPixels: w * h,
                modulePxAtZxing: codeSideAtZxing / s.modules,
                ms,
                coverage: coverage(back, gt),
            })
        }
        if ((i + 1) % 50 === 0) {
            console.error(`  ${i + 1}/${Math.min(limit, samples.length)}`)
        }
    }

    const label = arg('label') ?? 'code-bench'
    await mkdir(join(ROOT, 'out/code-bench'), { recursive: true })
    await writeFile(join(ROOT, `out/code-bench/${label}.json`), JSON.stringify(results))
    report(results)
}

function report(results: Result[]): void {
    const points = [...new Set(results.map((r) => r.point))]
    const images = new Set(results.map((r) => r.file)).size
    const leakable = new Set(results.filter((r) => r.leakable).map((r) => r.file)).size
    console.log(`\n${images} images, ${leakable} with a code still decodable from the stored image\n`)
    console.log(
        `  ${'point'.padEnd(8)}${'zxing MP'.padStart(10)}${'ms/img'.padStart(9)}${'leakable covered'.padStart(18)}${'all covered'.padStart(13)}`
    )
    const mean = (xs: number[]): number => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length)
    for (const point of points) {
        const rs = results.filter((r) => r.point === point)
        const leak = rs.filter((r) => r.leakable)
        const covered = leak.filter((r) => r.coverage >= COVERED).length
        console.log(
            `  ${point.padEnd(8)}${(mean(rs.map((r) => r.zxingPixels)) / 1e6).toFixed(3).padStart(10)}${mean(
                rs.map((r) => r.ms)
            )
                .toFixed(1)
                .padStart(9)}` +
                `${`${covered}/${leak.length}`.padStart(18)}${`${rs.filter((r) => r.coverage >= COVERED).length}/${rs.length}`.padStart(13)}`
        )
    }
    console.log('\n  leakable codes missed, by point and format')
    for (const point of points) {
        const missed = results.filter((r) => r.point === point && r.leakable && r.coverage < COVERED)
        if (missed.length) {
            const byFormat = new Map<string, number>()
            for (const r of missed) {
                byFormat.set(`${r.format}/${r.degradation}`, (byFormat.get(`${r.format}/${r.degradation}`) ?? 0) + 1)
            }
            console.log(`    ${point.padEnd(8)}${[...byFormat].map(([k, v]) => `${k}:${v}`).join('  ')}`)
        }
    }
    console.log('\n  detection rate by module size at the zxing input (px per module), all points pooled')
    const edges = [0, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 1e9]
    for (const format of new Set(results.map((r) => r.format))) {
        const cells = edges.slice(0, -1).map((lo, i) => {
            const b = results.filter(
                (r) => r.format === format && r.modulePxAtZxing >= lo && r.modulePxAtZxing < edges[i + 1]
            )
            return (
                b.length >= 10
                    ? `${Math.round((100 * b.filter((r) => r.coverage >= COVERED).length) / b.length)}%`
                    : '.'
            ).padStart(7)
        })
        console.log(`    ${format.padEnd(12)}${cells.join('')}`)
    }
    console.log(
        `    ${''.padEnd(12)}${edges
            .slice(0, -1)
            .map((lo, i) => `${lo}-${edges[i + 1] === 1e9 ? '' : edges[i + 1]}`.padStart(7))
            .join('')}`
    )
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
