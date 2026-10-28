import type { RecordedRequest } from './fake-server'

// Rewrites only what is random by design, so the rest can be compared byte for byte:
// - upload run and attempt ids (UUIDv7) become <run> and <attempt-n>,
// - the keys of `content_hashes` and release `metadata`, which Rust writes in HashMap order, are sorted,
// - `symbol_sets` lists are sorted by chunk id, because posthog-cli walks folders in file-system order,
// - object-storage uploads inside one batch are sorted by path and object key, because they run in parallel,
// - the multipart boundary, the user agent and object-storage headers are dropped.
// The user agent differs on purpose: hog sends `hog/<version>`, posthog-cli sends `posthog-cli`.
export interface NormalizedRequest {
    method: string
    path: string
    headers: Record<string, string>
    body?: string
    upload?: RecordedRequest['upload']
    status: number
}

function sortKeys(object: Record<string, unknown>): Record<string, unknown> {
    return Object.fromEntries(
        Object.keys(object)
            .sort()
            .map((key) => [key, object[key]])
    )
}

export function normalize(requests: RecordedRequest[]): NormalizedRequest[] {
    const attempts = new Map<string, string>()
    const out: NormalizedRequest[] = requests.map((request) => {
        const isStorage = request.path.startsWith('/s3/')
        const headers: Record<string, string> = isStorage
            ? { authorization: request.headers.authorization ?? '<none>' }
            : {
                  authorization: request.headers.authorization ?? '<none>',
                  'content-type': (request.headers['content-type'] ?? '<none>').replace(/;\s*boundary=.*/, ''),
              }
        let body = request.body
        if (body) {
            const parsed = JSON.parse(body) as Record<string, unknown>
            if ('upload_run_id' in parsed) {
                parsed.upload_run_id = '<run>'
            }
            if (typeof parsed.upload_attempt_id === 'string') {
                if (!attempts.has(parsed.upload_attempt_id)) {
                    attempts.set(parsed.upload_attempt_id, `<attempt-${attempts.size + 1}>`)
                }
                parsed.upload_attempt_id = attempts.get(parsed.upload_attempt_id)
            }
            if (parsed.content_hashes && typeof parsed.content_hashes === 'object') {
                parsed.content_hashes = sortKeys(parsed.content_hashes as Record<string, unknown>)
            }
            if (Array.isArray(parsed.symbol_sets)) {
                parsed.symbol_sets = [...(parsed.symbol_sets as { chunk_id: string }[])].sort((a, b) =>
                    a.chunk_id < b.chunk_id ? -1 : 1
                )
            }
            if (parsed.metadata && typeof parsed.metadata === 'object') {
                parsed.metadata = sortKeys(parsed.metadata as Record<string, unknown>)
            }
            body = JSON.stringify(parsed)
        }
        const upload = request.upload && {
            ...request.upload,
            fields: request.upload.fields && (sortKeys(request.upload.fields) as Record<string, string>),
        }
        return {
            method: request.method,
            path: request.path,
            headers,
            ...(body ? { body } : {}),
            ...(upload ? { upload } : {}),
            status: request.status,
        }
    })
    for (let start = 0; start < out.length; start++) {
        if (!out[start]!.path.startsWith('/s3/')) {
            continue
        }
        let end = start
        while (end < out.length && out[end]!.path.startsWith('/s3/')) {
            end++
        }
        const order = (request: NormalizedRequest): string => `${request.path} ${request.upload?.fields?.key ?? ''}`
        out.splice(start, end - start, ...out.slice(start, end).sort((a, b) => (order(a) < order(b) ? -1 : 1)))
        start = end
    }
    return out
}
