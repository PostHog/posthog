/**
 * Copies the models in models.json into the S3 mirror that the image build reads. Run it by hand with
 * the ml-prod-us-write profile before you push a models.json change, because CI can only read.
 *
 *   tsx dev/mirror-models.ts
 */
import { spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { type ManifestModel, assertPinnedSha256, readModelManifest } from './model-manifest.ts'

const WRITE_PROFILE = 'ml-prod-us-write'
const UA = 'Mozilla/5.0 posthog-replay-image-scrub' // HF + most CDNs reject requests without one

const manifest = readModelManifest()
const scratchDir = mkdtempSync(join(tmpdir(), 'mirror-models-'))

interface BucketPlacement {
    model: ManifestModel
    revisionDir: string
    revision: string
    pathInRevision: string
}

// The bucket keeps each upstream revision under <vendor>/<model>/<revision>/ with the upstream layout below it,
// and records where those files came from at _provenance/<vendor>/<model>/<revision>/checksums.tsv.
function placeInBucket(model: ManifestModel): BucketPlacement {
    const [vendor, name, revision, ...pathParts] = model.s3Key.split('/')
    if (!vendor || !name || !revision || pathParts.length === 0) {
        throw new Error(`${model.path}: s3Key ${model.s3Key} is not <vendor>/<model>/<revision>/<path>`)
    }
    return { model, revisionDir: `${vendor}/${name}/${revision}`, revision, pathInRevision: pathParts.join('/') }
}

function s3Url(key: string): string {
    return `s3://${manifest.bucket}/${key}`
}

function aws(args: string[]): { ok: boolean; stdout: Buffer; stderr: string } {
    const result = spawnSync('aws', [...args, '--profile', WRITE_PROFILE, '--region', manifest.region], {
        maxBuffer: 2 ** 30,
    })
    if (result.error) {
        throw result.error
    }
    return { ok: result.status === 0, stdout: result.stdout, stderr: result.stderr.toString() }
}

function putIfAbsent(key: string, body: Buffer | string): boolean {
    const bodyFile = join(scratchDir, 'body')
    writeFileSync(bodyFile, body)
    const put = aws([
        's3api',
        'put-object',
        '--bucket',
        manifest.bucket,
        '--key',
        key,
        '--body',
        bodyFile,
        '--if-none-match',
        '*',
    ])
    if (put.ok) {
        return true
    }
    if (put.stderr.includes('(PreconditionFailed)')) {
        return false
    }
    throw new Error(`put-object ${s3Url(key)} failed: ${put.stderr}`)
}

function readObject(key: string): Buffer {
    const get = aws(['s3', 'cp', s3Url(key), '-', '--only-show-errors'])
    if (!get.ok) {
        throw new Error(`reading ${s3Url(key)} failed: ${get.stderr}`)
    }
    return get.stdout
}

async function downloadUpstream(model: ManifestModel): Promise<Buffer> {
    const res = await fetch(model.upstreamUrl, { signal: AbortSignal.timeout(120_000), headers: { 'user-agent': UA } })
    if (!res.ok) {
        throw new Error(`${model.upstreamUrl}: status ${res.status}`)
    }
    return Buffer.from(await res.arrayBuffer())
}

function checksumRows(record: string): string {
    return record
        .split('\n')
        .filter((line) => line !== '' && !line.startsWith('#'))
        .sort()
        .join('\n')
}

async function main(): Promise<void> {
    const capturedUtc = new Date()
        .toISOString()
        .replace(/[-:]/g, '')
        .replace(/\.\d+Z$/, 'Z')
    const placements = manifest.models.map(placeInBucket)

    const provenanceByRevisionDir = new Map<string, { upstreamLines: string[]; rows: string[] }>()
    for (const { model, revisionDir, revision, pathInRevision } of placements) {
        const bytes = await downloadUpstream(model)
        assertPinnedSha256(model, bytes, model.upstreamUrl)
        if (putIfAbsent(model.s3Key, bytes)) {
            console.log(`created ${s3Url(model.s3Key)}`)
        } else {
            assertPinnedSha256(model, readObject(model.s3Key), s3Url(model.s3Key))
            console.log(`already mirrored ${s3Url(model.s3Key)}`)
        }
        const provenance = provenanceByRevisionDir.get(revisionDir) ?? { upstreamLines: [], rows: [] }
        provenance.upstreamLines.push(`# upstream: ${model.upstreamUrl} (revision ${revision})`)
        provenance.rows.push([pathInRevision, 'sha256', model.sha256, bytes.length].join('\t'))
        provenanceByRevisionDir.set(revisionDir, provenance)
    }

    for (const [revisionDir, { upstreamLines, rows }] of provenanceByRevisionDir) {
        const key = `_provenance/${revisionDir}/checksums.tsv`
        const record = [
            ...upstreamLines,
            `# captured: ${capturedUtc}`,
            '# columns: path<TAB>algo<TAB>expected_hash<TAB>size_bytes',
            ...rows,
            '',
        ].join('\n')
        if (putIfAbsent(key, record)) {
            console.log(`created ${s3Url(key)}`)
        } else if (checksumRows(readObject(key).toString('utf8')) === checksumRows(record)) {
            console.log(`provenance already recorded at ${s3Url(key)}`)
        } else {
            throw new Error(`${s3Url(key)} already exists with different checksum rows; compare it with models.json`)
        }
    }
}

main()
    .catch((e) => {
        console.error(e)
        process.exitCode = 1
    })
    .finally(() => rmSync(scratchDir, { recursive: true, force: true }))
