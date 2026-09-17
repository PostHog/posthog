import { createHash } from 'node:crypto'

import { sessionStartMonth } from '~/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format'

export const ML_KEY_SHARDS = 32
export const INGESTION_VERSION_HEADER = 'ai_research_ingestion_version'

/** Value of {@link INGESTION_VERSION_HEADER}: '2' carries an encrypted envelope, '1' carries cleartext. */
export type MlWireVersion = '1' | '2'

export interface MlSessionIdentity {
    teamId: number
    sessionId: string
}

export interface MlKeyIdentity {
    teamId: number
    sessionId?: string
    sessionMonth?: string
    /** Only on keys wrapped while the organization was part of the KMS context. A team can change organization mid-session, so new keys leave it out, and a stored key carries the one it was wrapped under. */
    organizationId?: string
}

export interface TableKey {
    pk: string
    sk: string
}

export function identityDigest(value: string): string {
    return createHash('sha256').update(value).digest('hex')
}

export function sessionShard(sessionId: string): number {
    return Number.parseInt(identityDigest(sessionId).slice(0, 8), 16) % ML_KEY_SHARDS
}

const SESSION_KEY_PREFIX = 'session:'
const IMAGE_KEY_PREFIX = 'image:'

export function sessionKeyId(teamId: number, sessionId: string): TableKey {
    return { pk: `team:${teamId}:shard:${sessionShard(sessionId)}`, sk: `${SESSION_KEY_PREFIX}${sessionId}` }
}

export function imageKeyId(teamId: number, sessionMonth: string): TableKey {
    return { pk: `team:${teamId}`, sk: `${IMAGE_KEY_PREFIX}${sessionMonth}` }
}

export function keySessionMonth(identity: MlKeyIdentity): string {
    if (identity.sessionId) {
        return sessionStartMonth(identity.sessionId)
    }
    if (!identity.sessionMonth || !/^[0-9]{4}-(0[1-9]|1[0-2])$/.test(identity.sessionMonth)) {
        throw new Error('ML image key requires a session month')
    }
    return identity.sessionMonth
}

export function monthKeyIndexId(identity: MlKeyIdentity, key: TableKey): TableKey {
    const id = tableKeyString(key)
    return { pk: `month:${keySessionMonth(identity)}:shard:${sessionShard(id)}`, sk: `key:${id}` }
}

// A stored key row is written once and never rewritten, unlike a team block row or a tombstone, which a deletion adds later.
export function holdsStoredKey(key: TableKey): boolean {
    return key.sk.startsWith(SESSION_KEY_PREFIX) || key.sk.startsWith(IMAGE_KEY_PREFIX)
}

export function storedSessionId(sortKey: string): string | undefined {
    return sortKey.startsWith(SESSION_KEY_PREFIX) ? sortKey.slice(SESSION_KEY_PREFIX.length) : undefined
}

export function teamBlockId(teamId: number): TableKey {
    return { pk: `team:${teamId}`, sk: 'deleted' }
}

export function tableKeyString(key: TableKey): string {
    return JSON.stringify([key.pk, key.sk])
}

export function wrappingContext(identity: MlKeyIdentity): Record<string, string> {
    return {
        purpose: identity.sessionId ? 'ai-research-session' : 'ai-research-image',
        team_id: String(identity.teamId),
        ...(identity.organizationId ? { organization_id: identity.organizationId } : {}),
        ...(identity.sessionId ? { session_id: identity.sessionId } : {}),
        ...(identity.sessionMonth ? { session_month: identity.sessionMonth } : {}),
    }
}
