import { spawnSync } from 'node:child_process'
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
import { dirname } from 'node:path'
import sharp from 'sharp'

import { assertPinnedSha256, readModelManifest } from './model-manifest.ts'

const ROOT = new URL('..', import.meta.url).pathname

// PostHog engineers have this profile and read the models from the S3 mirror that the image build uses.
// Everyone else falls back to the upstream URLs, and both paths check the same pinned sha256.
const MODELS_AWS_PROFILE = 'ml-prod-us'

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

/** Returns null when the read fails for any reason: no aws CLI, no profile, an expired login, or no object. */
function readFromS3Mirror(s3Url: string, region: string): Buffer | null {
    const result = spawnSync(
        'aws',
        ['s3', 'cp', s3Url, '-', '--only-show-errors', '--profile', MODELS_AWS_PROFILE, '--region', region],
        { maxBuffer: 2 ** 30, timeout: 300_000 }
    )
    if (result.status === 0) {
        return result.stdout
    }
    console.warn(`  cannot read ${s3Url}: ${result.error?.message ?? result.stderr.toString().trim()}`)
    return null
}

async function downloadModels(): Promise<void> {
    const manifest = readModelManifest()
    for (const model of manifest.models) {
        const dest = ROOT + model.path
        if (existsSync(dest)) {
            continue
        }
        const s3Url = `s3://${manifest.bucket}/${model.s3Key}`
        const fromS3Mirror = readFromS3Mirror(s3Url, manifest.region)
        if (!fromS3Mirror) {
            console.warn(`  ${model.path}: downloading ${model.upstreamUrl} instead`)
        }
        const bytes = fromS3Mirror ?? (await getBuf(model.upstreamUrl))
        assertPinnedSha256(model, bytes, fromS3Mirror ? s3Url : model.upstreamUrl)
        await mkdir(dirname(dest), { recursive: true })
        await writeFile(dest, bytes)
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
