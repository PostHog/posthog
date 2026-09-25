/**
 * Copies the models in models.json into the S3 mirror that the image build reads. Run it by hand with
 * the ml-prod-us-write profile before you push a models.json change, because CI can only read.
 *
 *   tsx dev/mirror-models.ts
 */
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
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

interface ProvenanceEntry {
    pathInRevision: string
    upstreamLine: string
    checksumRow: string
}

interface StoredObject {
    body: Buffer
    etag: string
}

interface ProvenanceWrite {
    key: string
    record: string
    existingEtag: string | null
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

function putObject(key: string, body: Buffer | string, precondition: string[]): boolean {
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
        ...precondition,
    ])
    if (put.ok) {
        return true
    }
    if (put.stderr.includes('(PreconditionFailed)') || put.stderr.includes('(ConditionalRequestConflict)')) {
        return false
    }
    throw new Error(`put-object ${s3Url(key)} failed: ${put.stderr}`)
}

function putIfAbsent(key: string, body: Buffer | string): boolean {
    return putObject(key, body, ['--if-none-match', '*'])
}

function putIfUnchanged(key: string, body: Buffer | string, etag: string): boolean {
    return putObject(key, body, ['--if-match', etag])
}

function readObjectIfPresent(key: string): StoredObject | null {
    const bodyFile = join(scratchDir, 'stored')
    const get = aws(['s3api', 'get-object', '--bucket', manifest.bucket, '--key', key, '--output', 'json', bodyFile])
    if (get.stderr.includes('(NoSuchKey)')) {
        return null
    }
    if (!get.ok) {
        throw new Error(`reading ${s3Url(key)} failed: ${get.stderr}`)
    }
    const { ETag } = JSON.parse(get.stdout.toString('utf8')) as { ETag: string }
    return { body: readFileSync(bodyFile), etag: ETag }
}

function readObject(key: string): Buffer {
    const stored = readObjectIfPresent(key)
    if (!stored) {
        throw new Error(`${s3Url(key)} does not exist`)
    }
    return stored.body
}

async function downloadUpstream(model: ManifestModel): Promise<Buffer> {
    const res = await fetch(model.upstreamUrl, { signal: AbortSignal.timeout(120_000), headers: { 'user-agent': UA } })
    if (!res.ok) {
        throw new Error(`${model.upstreamUrl}: status ${res.status}`)
    }
    return Buffer.from(await res.arrayBuffer())
}

function checksumRowsByPath(record: string): Map<string, string> {
    const rows = record.split('\n').filter((line) => line !== '' && !line.startsWith('#'))
    return new Map(rows.map((row) => [row.split('\t')[0], row]))
}

function provenanceBlock(entries: ProvenanceEntry[], capturedUtc: string): string {
    return [
        ...entries.map((entry) => entry.upstreamLine),
        `# captured: ${capturedUtc}`,
        '# columns: path<TAB>algo<TAB>expected_hash<TAB>size_bytes',
        ...entries.map((entry) => entry.checksumRow),
        '',
    ].join('\n')
}

function planProvenanceWrite(key: string, entries: ProvenanceEntry[], capturedUtc: string): ProvenanceWrite | null {
    const stored = readObjectIfPresent(key)
    if (!stored) {
        return { key, record: provenanceBlock(entries, capturedUtc), existingEtag: null }
    }
    const storedRecord = stored.body.toString('utf8')
    const storedRows = checksumRowsByPath(storedRecord)
    const unrecorded: ProvenanceEntry[] = []
    for (const entry of entries) {
        const storedRow = storedRows.get(entry.pathInRevision)
        if (storedRow === undefined) {
            unrecorded.push(entry)
        } else if (storedRow !== entry.checksumRow) {
            throw new Error(
                `${s3Url(key)} records ${entry.pathInRevision} with other checksum values; compare it with models.json`
            )
        }
    }
    if (unrecorded.length === 0) {
        return null
    }
    // Append a block instead of rewriting the record, so that the rows an earlier run recorded keep their own capture time.
    const separator = storedRecord.endsWith('\n') ? '' : '\n'
    return {
        key,
        record: storedRecord + separator + provenanceBlock(unrecorded, capturedUtc),
        existingEtag: stored.etag,
    }
}

async function main(): Promise<void> {
    const capturedUtc = new Date()
        .toISOString()
        .replace(/[-:]/g, '')
        .replace(/\.\d+Z$/, 'Z')

    const upstreamModels: { model: ManifestModel; bytes: Buffer }[] = []
    const provenanceByRevisionDir = new Map<string, ProvenanceEntry[]>()
    for (const { model, revisionDir, revision, pathInRevision } of manifest.models.map(placeInBucket)) {
        const bytes = await downloadUpstream(model)
        assertPinnedSha256(model, bytes, model.upstreamUrl)
        upstreamModels.push({ model, bytes })
        const entries = provenanceByRevisionDir.get(revisionDir) ?? []
        entries.push({
            pathInRevision,
            upstreamLine: `# upstream: ${model.upstreamUrl} (revision ${revision})`,
            checksumRow: [pathInRevision, 'sha256', model.sha256, bytes.length].join('\t'),
        })
        provenanceByRevisionDir.set(revisionDir, entries)
    }

    // Check every provenance record before the first upload, so that a record that disagrees with models.json stops the run before it creates an object.
    const provenanceWrites: ProvenanceWrite[] = []
    for (const [revisionDir, entries] of provenanceByRevisionDir) {
        const key = `_provenance/${revisionDir}/checksums.tsv`
        const write = planProvenanceWrite(key, entries, capturedUtc)
        if (write) {
            provenanceWrites.push(write)
        } else {
            console.log(`provenance already recorded at ${s3Url(key)}`)
        }
    }

    for (const { model, bytes } of upstreamModels) {
        if (putIfAbsent(model.s3Key, bytes)) {
            console.log(`created ${s3Url(model.s3Key)}`)
        } else {
            assertPinnedSha256(model, readObject(model.s3Key), s3Url(model.s3Key))
            console.log(`already mirrored ${s3Url(model.s3Key)}`)
        }
    }

    for (const { key, record, existingEtag } of provenanceWrites) {
        const written = existingEtag === null ? putIfAbsent(key, record) : putIfUnchanged(key, record, existingEtag)
        if (!written) {
            throw new Error(`${s3Url(key)} changed while this run was in progress, so run the script again`)
        }
        console.log(`${existingEtag === null ? 'created' : 'added rows to'} ${s3Url(key)}`)
    }
}

main()
    .catch((e) => {
        console.error(e)
        process.exitCode = 1
    })
    .finally(() => rmSync(scratchDir, { recursive: true, force: true }))
