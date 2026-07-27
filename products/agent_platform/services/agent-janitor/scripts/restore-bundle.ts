import { DeleteObjectCommand, S3Client } from '@aws-sdk/client-s3'
/**
 * One-off: restore a frozen revision's bundle into S3 from one of the
 * example bundle dirs on disk.
 *
 * Why this exists: when the bundle store moved from FS to S3 (commit
 * 9e702c607c6), local revisions that were already frozen lost their bundle
 * content. The S3 bucket is empty; the DB still says the revision is frozen.
 * This script copies an on-disk example bundle into S3 under a given
 * revision id so the runner can load the bundle at session start.
 *
 * Usage (from posthog repo root):
 *
 *   pnpm --filter @posthog/agent-janitor exec tsx \
 *     scripts/restore-bundle.ts --rev <revision-id> --from <example-dir> [--freeze]
 *
 * Example dirs live in services/agent-tests/src/examples/ (agent-builder,
 * sre-slack-bot). Pass the absolute or repo-relative path.
 *
 * To find revision ids:
 *
 *   psql posthog -c "
 *     SELECT r.id, a.slug, r.state
 *     FROM agent_revision r
 *     JOIN agent_application a ON r.application_id = a.id
 *     WHERE r.state IN ('frozen','published')
 *     ORDER BY r.created_at DESC;
 *   "
 *
 * Env: reads AGENT_BUNDLE_S3_* — the same vars the runner and janitor use.
 * In dev, falls back to the local SeaweedFS defaults below (matches the
 * isDev gates in agent-{runner,janitor}/src/config.ts). Update all three
 * together if the dev S3 endpoint moves again.
 */
import { readFile, readdir, stat } from 'node:fs/promises'
import path from 'node:path'

import { S3BundleStore } from '@posthog/agent-shared'

// Keep these in sync with services/agent-{runner,janitor}/src/config.ts.
const DEV_S3_ENDPOINT = 'http://localhost:8333'
const DEV_S3_BUCKET = 'posthog'
const DEV_S3_ACCESS_KEY_ID = 'any'
const DEV_S3_SECRET_ACCESS_KEY = 'any'

const isDev = (): boolean => process.env.NODE_ENV !== 'production'

interface Args {
    rev: string
    from: string
    freeze: boolean
    force: boolean
}

function parseArgs(): Args {
    const args: Partial<Args> = { freeze: false, force: false }
    for (let i = 2; i < process.argv.length; i++) {
        const v = process.argv[i]
        switch (v) {
            case '--rev':
                args.rev = process.argv[++i]
                break
            case '--from':
                args.from = process.argv[++i]
                break
            case '--freeze':
                args.freeze = true
                break
            case '--force':
                // Delete the .frozen marker before writing. Use when a
                // previous restore attempt completed --freeze but you want
                // to overwrite the bundle (e.g. wrong source dir).
                args.force = true
                break
            default:
                throw new Error(`unknown arg ${v}`)
        }
    }
    if (!args.rev || !args.from) {
        throw new Error('usage: --rev <id> --from <example-dir> [--freeze] [--force]')
    }
    return args as Args
}

// Skip files that aren't bundle content:
// - README.md   — author notes for the on-disk example dirs
// - .frozen     — bundle-store internal marker; `--freeze` writes its own
const SKIP_FILES = new Set(['README.md', '.frozen'])
const SKIP_DIRS = new Set(['tests', 'node_modules', '.git'])

async function* walkFiles(root: string, sub = ''): AsyncGenerator<{ abs: string; rel: string }> {
    const dirAbs = path.join(root, sub)
    for (const entry of await readdir(dirAbs, { withFileTypes: true })) {
        const rel = sub ? path.join(sub, entry.name) : entry.name
        if (entry.isDirectory()) {
            if (SKIP_DIRS.has(entry.name)) {
                continue
            }
            yield* walkFiles(root, rel)
        } else if (entry.isFile() && !SKIP_FILES.has(entry.name)) {
            yield { abs: path.join(root, rel), rel }
        }
    }
}

async function main(): Promise<void> {
    const { rev, from, freeze, force } = parseArgs()

    const fromStat = await stat(from).catch(() => null)
    if (!fromStat?.isDirectory()) {
        throw new Error(`--from must be a directory: ${from}`)
    }

    const endpoint = process.env.AGENT_BUNDLE_S3_ENDPOINT ?? (isDev() ? DEV_S3_ENDPOINT : undefined)
    const region = process.env.AGENT_BUNDLE_S3_REGION ?? 'us-east-1'
    const bucket = process.env.AGENT_BUNDLE_S3_BUCKET ?? (isDev() ? DEV_S3_BUCKET : undefined)
    const bucketPrefix = process.env.AGENT_BUNDLE_S3_PREFIX
    const accessKeyId = process.env.AGENT_BUNDLE_S3_ACCESS_KEY_ID ?? (isDev() ? DEV_S3_ACCESS_KEY_ID : undefined)
    const secretAccessKey =
        process.env.AGENT_BUNDLE_S3_SECRET_ACCESS_KEY ?? (isDev() ? DEV_S3_SECRET_ACCESS_KEY : undefined)
    const forcePathStyle = process.env.AGENT_BUNDLE_S3_FORCE_PATH_STYLE !== 'false' // default true (SeaweedFS + MinIO both need this)

    if (!bucket) {
        throw new Error('AGENT_BUNDLE_S3_BUCKET is required (no dev fallback when NODE_ENV=production)')
    }

    const client = new S3Client({
        endpoint,
        region,
        credentials: accessKeyId && secretAccessKey ? { accessKeyId, secretAccessKey } : undefined,
        forcePathStyle,
    })
    const store = new S3BundleStore({ client, bucket, bucketPrefix })

    if (force) {
        // Clear the .frozen marker so S3BundleStore.write() doesn't refuse.
        // Has to bypass the BundleStore — its own delete() also refuses on
        // frozen bundles, so we go straight to the SDK.
        const prefix = (bucketPrefix ?? 'agent_bundles').replace(/^\/+|\/+$/g, '')
        const frozenKey = `${prefix}/${rev}/.frozen`
        await client.send(new DeleteObjectCommand({ Bucket: bucket, Key: frozenKey }))
    }

    for await (const { abs, rel } of walkFiles(from)) {
        const content = await readFile(abs, 'utf8')
        const bundlePath = rel.split(path.sep).join('/')
        await store.write(rev, bundlePath, content)
    }

    if (freeze) {
        await store.freeze(rev)
    }
}

main().catch((err) => {
    console.error(err)
    process.exit(1)
})
