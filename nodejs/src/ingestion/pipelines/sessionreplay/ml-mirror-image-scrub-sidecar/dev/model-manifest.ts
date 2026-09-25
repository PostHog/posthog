import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'

export interface ManifestModel {
    /** Relative to the sidecar dir, which is also WORKDIR in the image. */
    path: string
    s3Key: string
    sha256: string
    upstreamUrl: string
}

export interface ModelManifest {
    bucket: string
    region: string
    models: ManifestModel[]
}

export function readModelManifest(): ModelManifest {
    return JSON.parse(readFileSync(new URL('../models.json', import.meta.url), 'utf8')) as ModelManifest
}

// The models decide what gets redacted, so a file that differs from its pinned digest is never used. An upstream
// change or a compromise could otherwise swap the anonymization control silently.
export function assertPinnedSha256(model: ManifestModel, bytes: Uint8Array, source: string): void {
    const actualSha256 = createHash('sha256').update(bytes).digest('hex')
    if (actualSha256 !== model.sha256) {
        throw new Error(
            `${model.path} from ${source}: sha256 ${actualSha256} does not match models.json (${model.sha256}), refusing to use it`
        )
    }
}
