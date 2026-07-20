import { createHash } from 'node:crypto'
import { existsSync } from 'node:fs'
/**
 * One-time setup: download the ONNX models and a bounded sample of real test images (faces + text),
 * then generate the synthetic corpus. Nothing here is committed (see .gitignore) — rerun any time.
 *
 *   npm run setup
 *
 * Test images come from the HuggingFace datasets-server REST API (no Python / `datasets` needed):
 * /splits discovers a valid config+split, /rows returns rows whose image cells carry a `src` URL.
 * The dataset list below is just defaults — swap in whatever faces/text sources you want.
 */
import { mkdir, writeFile } from 'node:fs/promises'
import sharp from 'sharp'

const ROOT = new URL('..', import.meta.url).pathname

// The models decide what gets redacted, so they're pinned to immutable refs and digest-verified —
// a mutable `main` URL would let an upstream change (or compromise) silently swap the privacy
// control. Keep URLs + digests in sync with Dockerfile.ml-mirror-image-scrub (the image bakes the
// same files at build time).
const MODELS: { url: string; file: string; sha256: string }[] = [
    {
        url: 'https://huggingface.co/SWHL/RapidOCR/resolve/1cfba2e90fc938db55889873735088de210cc173/PP-OCRv4/en_PP-OCRv3_det_infer.onnx',
        file: 'models/dbnet_det.onnx',
        sha256: 'f139598bc2af4e4b6fe98dec11574e30edfdd91fc94ac1425c18ace3bd5a866b',
    },
    {
        url: 'https://github.com/opencv/opencv_zoo/raw/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet/face_detection_yunet_2023mar.onnx',
        file: 'models/yunet.onnx',
        sha256: '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4',
    },
    {
        url: 'https://huggingface.co/OwenElliott/image-safety-classifier-xs/resolve/54f4560bd9c5ee92d45dc30418a8f8680e80de6d/onnx/image-safety-classifier-xs.onnx',
        file: 'models/safety.onnx',
        sha256: '8c28c49d9075f3ad15ebdc2961f02d5b3f99be944815b848b49c9f0e6f3fb689',
    },
]

// HuggingFace datasets to sample (verified reachable via datasets-server). Faces: real faces. Text:
// dense text + PII-like fields. Swap in others (RICO/WebUI screenshots, COCO-Text/ICDAR scene text).
// Verified: /rows returns an image whose asset URL actually fetches (some datasets' presigned
// cached-asset URLs 403, e.g. flwrlabs/celeba — avoid those).
const DATASETS: { dataset: string; dir: string; count: number }[] = [
    { dataset: 'tonyassi/celebrity-1000', dir: 'test-data/faces', count: 50 }, // real celebrity faces
    { dataset: 'logasja/lfw', dir: 'test-data/faces', count: 30 }, // Labeled Faces in the Wild
    { dataset: 'nielsr/funsd', dir: 'test-data/text', count: 20 }, // forms — dense text + PII-like fields
]

const UA = 'Mozilla/5.0 posthog-replay-image-scrub' // HF + most CDNs reject requests without one

async function get(url: string): Promise<Response> {
    return fetch(url, { signal: AbortSignal.timeout(60000), headers: { 'user-agent': UA } })
}

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))

/** GET JSON with retries; the datasets-server intermittently returns HTML error pages on flaky links. */
async function getJson(url: string, tries = 3): Promise<any> {
    for (let i = 0; i < tries; i++) {
        try {
            const text = await (await get(url)).text()
            return JSON.parse(text) // throws on an HTML error page -> retry
        } catch (e) {
            if (i === tries - 1) {
                throw e
            }
            await sleep(1000 * (i + 1))
        }
    }
}

async function getBuf(url: string, tries = 3): Promise<Buffer> {
    for (let i = 0; i < tries; i++) {
        try {
            const res = await get(url)
            if (!res.ok) {
                throw new Error(`status ${res.status}`)
            }
            return Buffer.from(await res.arrayBuffer())
        } catch (e) {
            if (i === tries - 1) {
                throw e
            }
            await sleep(1000 * (i + 1))
        }
    }
    throw new Error('unreachable')
}

async function downloadModels(): Promise<void> {
    for (const m of MODELS) {
        const dest = ROOT + m.file
        if (existsSync(dest)) {
            continue
        }
        const buf = await getBuf(m.url)
        const digest = createHash('sha256').update(buf).digest('hex')
        if (digest !== m.sha256) {
            throw new Error(`${m.file}: sha256 mismatch (got ${digest}, want ${m.sha256}) — refusing to write`)
        }
        await mkdir(ROOT + 'models', { recursive: true })
        await writeFile(dest, buf)
    }
}

/** Find the first column in a datasets-server row whose value looks like an image ({ src }). */
function imageUrlOf(row: Record<string, unknown>): string | null {
    for (const v of Object.values(row)) {
        if (v && typeof v === 'object' && typeof (v as { src?: unknown }).src === 'string') {
            return (v as { src: string }).src
        }
    }
    return null
}

async function downloadHf(dataset: string, dir: string, count: number): Promise<number> {
    const splits = await getJson(`https://datasets-server.huggingface.co/splits?dataset=${encodeURIComponent(dataset)}`)
    const list: { config: string; split: string }[] = splits?.splits ?? []
    if (!list.length) {
        throw new Error(`no splits for ${dataset}`)
    }
    const pick = list.find((s) => /val|test/.test(s.split)) ?? list[0]
    const data = await getJson(
        `https://datasets-server.huggingface.co/rows?dataset=${encodeURIComponent(dataset)}&config=${encodeURIComponent(pick.config)}&split=${encodeURIComponent(pick.split)}&offset=0&length=${count}`
    )
    const rows = data?.rows ?? []
    await mkdir(ROOT + dir, { recursive: true })
    let n = 0
    for (const r of rows) {
        const url = imageUrlOf(r.row ?? {})
        if (!url) {
            continue
        }
        try {
            await sharp(await getBuf(url))
                .png()
                .toFile(`${ROOT}${dir}/${dataset.replace(/\W+/g, '_')}_${n}.png`)
            n++
        } catch {
            // skip a bad row
        }
    }
    return n
}

async function main(): Promise<void> {
    await downloadModels()

    let total = 0
    for (const d of DATASETS) {
        try {
            const n = await downloadHf(d.dataset, d.dir, d.count)
            total += n
        } catch (e) {
            console.warn(`  ${d.dataset}: failed (${String(e)})`)
        }
    }
    if (total === 0) {
        console.warn('no HF images fetched (network?); the suite will still run on the synthetic corpus')
    }

    await import('./make-corpus.ts')
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
