// The shared key between the producer, this consumer, and training joins; pseudo_team is the non-reversible
// HMAC team pseudonym from ml-mirror/pseudonymize.ts (keeps raw team ids out of the ML bucket).
import { createHash } from 'node:crypto'

const PREFIX = 'image'
const REF_RE = /^image:([0-9a-f]{32}):([A-Za-z0-9_-]{22})$/

export function hashImageBytes(bytes: Buffer): string {
    return createHash('sha256').update(bytes).digest('base64url').slice(0, 22)
}

export function imageRef(pseudoTeam: string, hash: string): string {
    return `${PREFIX}:${pseudoTeam}:${hash}`
}

export function isImageRef(s: string): boolean {
    return REF_RE.test(s)
}

export function parseImageRef(s: string): { pseudoTeam: string; hash: string } | null {
    const m = REF_RE.exec(s)
    return m ? { pseudoTeam: m[1], hash: m[2] } : null
}
