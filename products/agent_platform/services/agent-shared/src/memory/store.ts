/**
 * MemoryStore — the cross-process surface for agent memory files.
 *
 * Files are markdown with YAML frontmatter (see format.ts), keyed at
 *   agent_memory/team/<team_id>/agent/<application_slug>/<path>.md
 *
 * The store enforces the team/app prefix on every read and write — callers
 * pass `{ teamId, applicationId }` and a relative `<path>.md` and never
 * see the bucket prefix directly.
 *
 * Two impls:
 *   - InMemoryMemoryStore — Map-backed. Used by tests + dev when no bucket
 *     is configured.
 *   - S3MemoryStore — talks to S3 / SeaweedFS via @aws-sdk/client-s3.
 */

import { MemoryFrontmatter } from './format'

export interface MemoryScope {
    teamId: number
    applicationId: string
}

/** Metadata-only view, used by list + search ranking without paying for a full GET. */
export interface MemoryHeader {
    /** Path relative to the (team, app) prefix — what the tools accept and return. */
    path: string
    frontmatter: MemoryFrontmatter
}

export interface MemoryFile extends MemoryHeader {
    /** Body markdown (no frontmatter). */
    content: string
}

export interface PutOpts {
    /** When true, fail if the file already exists. Used by `create`. */
    failIfExists?: boolean
    /** When true, fail if the file does NOT exist. Used by `update`. */
    failIfMissing?: boolean
}

export interface MemoryStore {
    /** List files under the (team, app) prefix. Returns headers (frontmatter only). */
    list(scope: MemoryScope, opts?: { prefix?: string }): Promise<MemoryHeader[]>
    /** Read one file in full. Throws if missing. */
    read(scope: MemoryScope, path: string): Promise<MemoryFile>
    /** Read only the leading frontmatter for one file (cheap, used by search ranking). */
    readHeader(scope: MemoryScope, path: string): Promise<MemoryHeader>
    /** Write or overwrite. Body is the already-serialized markdown+frontmatter string. */
    put(scope: MemoryScope, path: string, raw: string, opts?: PutOpts): Promise<void>
    /** Hard delete. Throws if missing (callers should pre-check via exists() if they care). */
    delete(scope: MemoryScope, path: string): Promise<void>
    /** Cheap existence probe used by put() and the tools. */
    exists(scope: MemoryScope, path: string): Promise<boolean>
}

const PATH_RE = /^[a-z0-9][a-z0-9_/-]*\.md$/

/**
 * Validate a tool-facing path. Returns the path unchanged or throws.
 * - Strict ascii lowercase, digits, `_`, `-`, `/`.
 * - Must end in `.md`.
 * - No leading slash, no `..`, no `//`.
 * - First char must be alphanumeric.
 */
export function validateMemoryPath(path: string): string {
    if (!PATH_RE.test(path)) {
        throw new Error(`invalid memory path "${path}" — must match ${PATH_RE} (no .., no leading slash, no //)`)
    }
    if (path.includes('..') || path.includes('//')) {
        throw new Error(`invalid memory path "${path}" — must not contain ".." or "//"`)
    }
    return path
}

/**
 * Compose the full bucket key. Exported so the S3 impl can use it and tests
 * can assert against the wire format.
 */
export function keyFor(scope: MemoryScope, path: string, bucketPrefix: string): string {
    const trimmedPrefix = bucketPrefix.replace(/^\/+|\/+$/g, '')
    return `${trimmedPrefix}/team/${scope.teamId}/agent/${scope.applicationId}/${path}`
}

export function prefixFor(scope: MemoryScope, bucketPrefix: string, subPrefix?: string): string {
    const trimmedPrefix = bucketPrefix.replace(/^\/+|\/+$/g, '')
    const base = `${trimmedPrefix}/team/${scope.teamId}/agent/${scope.applicationId}/`
    if (!subPrefix) {
        return base
    }
    const sub = subPrefix.replace(/^\/+/, '')
    if (sub.includes('..')) {
        throw new Error(`invalid list prefix "${subPrefix}"`)
    }
    return base + sub
}

/**
 * Tools call this to surface "this isn't available yet". Used for the
 * cross-agent share gap (see plan doc). The shape matches the existing
 * approval-gated tool result envelope so the model can react to it.
 */
export const NOT_IMPLEMENTED_ERR = 'not_implemented_in_slice'

/** Thrown by store impls when a path can't be found. */
export class MemoryNotFoundError extends Error {
    constructor(public readonly path: string) {
        super(`memory file not found: ${path}`)
        this.name = 'MemoryNotFoundError'
    }
}

/** Thrown by store impls on a put() collision (create-existing or update-missing). */
export class MemoryConflictError extends Error {
    constructor(
        public readonly path: string,
        reason: string
    ) {
        super(`memory file conflict at ${path}: ${reason}`)
        this.name = 'MemoryConflictError'
    }
}
