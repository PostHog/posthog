/* eslint-disable no-console -- CLI output script: console output is the whole point */
/**
 * Downloads for dev/text-det-bench.ts: the candidate text detectors, and labelled images with a
 * ground-truth box per word. Nothing here is committed (models/ and test-data/ are gitignored).
 *
 *   tsx dev/text-det-setup.ts
 *
 * Every model is pinned by URL and sha256. The docTR exports have a fixed 1024x1024 input, so after
 * download run dev/text-det-dynamic-hw.py on them to make height and width dynamic.
 *
 * Ground truth is written as test-data/text-det/<set>/gt.json in one shape for every set, so the bench
 * never parses a dataset's own format.
 */
import { createHash } from 'node:crypto'
import { existsSync } from 'node:fs'
import { mkdir, writeFile } from 'node:fs/promises'
import sharp from 'sharp'

const ROOT = new URL('..', import.meta.url).pathname
const UA = 'Mozilla/5.0 posthog-replay-image-scrub'

const CANDIDATES: { file: string; url: string; sha256: string }[] = [
    {
        file: 'models/candidates/ppocrv3_det.onnx',
        url: 'https://huggingface.co/SWHL/RapidOCR/resolve/1cfba2e90fc938db55889873735088de210cc173/PP-OCRv4/en_PP-OCRv3_det_infer.onnx',
        sha256: 'f139598bc2af4e4b6fe98dec11574e30edfdd91fc94ac1425c18ace3bd5a866b',
    },
    {
        file: 'models/candidates/ppocrv4_mobile_det.onnx',
        url: 'https://huggingface.co/SWHL/RapidOCR/resolve/1cfba2e90fc938db55889873735088de210cc173/PP-OCRv4/ch_PP-OCRv4_det_infer.onnx',
        sha256: 'd2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9',
    },
    {
        file: 'models/candidates/ppocrv5_mobile_det.onnx',
        url: 'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/det/ch_PP-OCRv5_det_mobile.onnx',
        sha256: '4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae',
    },
    {
        file: 'models/candidates/ppocrv6_small_det.onnx',
        url: 'https://huggingface.co/PaddlePaddle/PP-OCRv6_small_det_onnx/resolve/28fe5895c24fd108c19eb3e8479f4ab385fbfc62/inference.onnx',
        sha256: 'd73e0058b7a8086bbd57f3d10b8bcd4ff95363f67e06e2762b5e814fe9c9410e',
    },
    {
        file: 'models/candidates/doctr_db_mobilenet_v3_large.onnx',
        url: 'https://github.com/felixdittrich92/OnnxTR/releases/download/v0.2.0/db_mobilenet_v3_large-4987e7bd.onnx',
        sha256: '4987e7bdea372559808bd5add85fda10e179dc639696fb489e59a197a25b4c64',
    },
    {
        file: 'models/candidates/doctr_db_mobilenet_v3_large_int8.onnx',
        url: 'https://github.com/felixdittrich92/OnnxTR/releases/download/v0.2.0/db_mobilenet_v3_large_static_8_bit-535a6f25.onnx',
        sha256: '535a6f253365f8ea6c187567463559d4278414519e1fc995e4b87f97600a7938',
    },
    {
        file: 'models/candidates/doctr_fast_tiny.onnx',
        url: 'https://github.com/felixdittrich92/OnnxTR/releases/download/v0.0.1/rep_fast_tiny-28867779.onnx',
        sha256: '2886777913e837ea3a5ab79f7fb9fd5db5897fc6560f21d16a4f54c64fc0b357',
    },
]

export interface GtWord {
    /** Axis-aligned, in the saved image's pixels: [left, top, right, bottom). */
    box: [number, number, number, number]
    text: string
    fontPx?: number
}

export interface GtImage {
    file: string
    width: number
    height: number
    words: GtWord[]
    /** How far a box edge can sit from the ink because of how the set stores coordinates. */
    tolerancePx: number
}

async function get(url: string): Promise<Response> {
    return fetch(url, { signal: AbortSignal.timeout(60000), headers: { 'user-agent': UA } })
}

async function getBuf(url: string, tries = 3): Promise<Buffer> {
    for (let i = 0; ; i++) {
        try {
            const res = await get(url)
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`)
            }
            return Buffer.from(await res.arrayBuffer())
        } catch (e) {
            if (i + 1 >= tries) {
                throw e
            }
            await new Promise((r) => setTimeout(r, 1000 * (i + 1)))
        }
    }
}

async function getJson(url: string): Promise<any> {
    return JSON.parse((await getBuf(url)).toString('utf8'))
}

async function downloadCandidates(): Promise<void> {
    await mkdir(ROOT + 'models/candidates', { recursive: true })
    for (const c of CANDIDATES) {
        if (existsSync(ROOT + c.file)) {
            continue
        }
        const buf = await getBuf(c.url)
        const digest = createHash('sha256').update(buf).digest('hex')
        if (digest !== c.sha256) {
            throw new Error(`${c.file}: sha256 ${digest} does not match the pinned ${c.sha256}`)
        }
        await writeFile(ROOT + c.file, buf)
        console.log(`  ${c.file} (${(buf.length / 1e6).toFixed(1)} MB)`)
    }
}

/** Rows from the HF datasets-server, 100 per request, which is its page limit. */
async function hfRows(dataset: string, split: string, count: number): Promise<Record<string, any>[]> {
    const rows: Record<string, any>[] = []
    for (let offset = 0; offset < count; offset += 100) {
        const length = Math.min(100, count - offset)
        const page = await getJson(
            `https://datasets-server.huggingface.co/rows?dataset=${encodeURIComponent(dataset)}&config=default&split=${split}&offset=${offset}&length=${length}`
        )
        rows.push(...(page.rows ?? []).map((r: { row: Record<string, any> }) => r.row))
    }
    return rows
}

async function saveSet(
    name: string,
    rows: Record<string, any>[],
    toWords: (row: Record<string, any>, width: number, height: number) => GtWord[],
    tolerancePx: (width: number, height: number) => number
): Promise<void> {
    const dir = `${ROOT}test-data/text-det/${name}`
    await mkdir(dir, { recursive: true })
    const images: GtImage[] = []
    for (const [i, row] of rows.entries()) {
        const bytes = await getBuf(row.image.src)
        const { width, height, format } = await sharp(bytes).metadata()
        // Kept in the served encoding when the pipeline accepts it, so photos stay JPEG as they would arrive.
        const keep = format === 'jpeg' || format === 'png'
        const file = `${name}_${String(i).padStart(3, '0')}.${keep ? (format === 'jpeg' ? 'jpg' : 'png') : 'png'}`
        await writeFile(`${dir}/${file}`, keep ? bytes : await sharp(bytes).png().toBuffer())
        const words = toWords(row, width!, height!).filter((w) => w.box[2] > w.box[0] && w.box[3] > w.box[1])
        images.push({ file, width: width!, height: height!, words, tolerancePx: tolerancePx(width!, height!) })
    }
    await writeFile(`${dir}/gt.json`, JSON.stringify(images))
    console.log(`  ${name}: ${images.length} images, ${images.reduce((n, im) => n + im.words.length, 0)} words`)
}

/** The born-digital set stores its annotation as a JSON-encoded string inside the row. */
function parseDumped(value: unknown): string {
    const text = String(value ?? '')
    return text.startsWith('"') ? String(JSON.parse(text)) : text
}

/** Web banners and ads (ICDAR 2013 born-digital). Coordinates are whole percent of each axis. */
async function bornDigital(count: number): Promise<void> {
    const rows = await hfRows('Berzerker/born_digital_images_dataset', 'train', count)
    await saveSet(
        'born-digital',
        rows,
        (row, width, height) =>
            parseDumped(row.output_json_dumpsed)
                .split('\n')
                .map((line) => line.trim().split(/\s+/))
                .filter((parts) => parts.length >= 5)
                .map((parts) => {
                    const [x0, y0, x1, y1] = parts.slice(0, 4).map(Number)
                    return {
                        box: [
                            Math.floor((x0 / 100) * width),
                            Math.floor((y0 / 100) * height),
                            Math.ceil((x1 / 100) * width),
                            Math.ceil((y1 / 100) * height),
                        ] as GtWord['box'],
                        text: parts.slice(4).join(' '),
                    }
                }),
        (width, height) => Math.ceil(Math.max(width, height) / 100)
    )
}

/** Scanned forms. Boxes are in LayoutLM's 0-1000 range on each axis, not pixels. */
async function funsd(count: number): Promise<void> {
    const rows = await hfRows('nielsr/funsd', 'test', count)
    await saveSet(
        'funsd',
        rows,
        (row, width, height) =>
            (row.words as string[]).map((text, i) => {
                const [x0, y0, x1, y1] = row.bboxes[i] as number[]
                return {
                    box: [
                        Math.floor((x0 / 1000) * width),
                        Math.floor((y0 / 1000) * height),
                        Math.ceil((x1 / 1000) * width),
                        Math.ceil((y1 / 1000) * height),
                    ] as GtWord['box'],
                    text,
                }
            }),
        (width, height) => Math.ceil(Math.max(width, height) / 1000)
    )
}

/** Receipt photos. Word quads are in the original image's pixels, which the server may have resized. */
async function cord(count: number): Promise<void> {
    const rows = await hfRows('naver-clova-ix/cord-v2', 'test', count)
    await saveSet(
        'cord',
        rows,
        (row, width, height) => {
            const gt = JSON.parse(row.ground_truth)
            const size = gt.meta?.image_size ?? { width, height }
            const sx = width / size.width
            const sy = height / size.height
            return (gt.valid_line ?? []).flatMap((line: any) =>
                (line.words ?? []).map((w: any) => {
                    const q = w.quad
                    const xs = [q.x1, q.x2, q.x3, q.x4]
                    const ys = [q.y1, q.y2, q.y3, q.y4]
                    return {
                        box: [
                            Math.floor(Math.min(...xs) * sx),
                            Math.floor(Math.min(...ys) * sy),
                            Math.ceil(Math.max(...xs) * sx),
                            Math.ceil(Math.max(...ys) * sy),
                        ] as GtWord['box'],
                        text: String(w.text ?? ''),
                    }
                })
            )
        },
        () => 2
    )
}

async function main(): Promise<void> {
    console.log('candidate models:')
    await downloadCandidates()
    console.log('labelled images:')
    for (const [name, fetchSet] of [
        ['born-digital', () => bornDigital(100)],
        ['funsd', () => funsd(50)],
        ['cord', () => cord(50)],
    ] as const) {
        if (existsSync(`${ROOT}test-data/text-det/${name}/gt.json`)) {
            continue
        }
        await fetchSet()
    }
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
