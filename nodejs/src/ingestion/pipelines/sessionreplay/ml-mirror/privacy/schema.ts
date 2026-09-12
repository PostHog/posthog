import { createHash } from 'node:crypto'

import { sessionStartMonth } from '~/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format'

export const ML_KEY_SHARDS = 32
export const INGESTION_VERSION_HEADER = 'ai_research_ingestion_version'
export const CONSENT_GRANTED_AT_HEADER = 'ai_research_consent_granted_at'

export interface MlSessionIdentity {
    teamId: number
    organizationId: string
    sessionId: string
    distinctId: string
}

export interface MlKeyIdentity {
    teamId: number
    organizationId: string
    sessionId?: string
    sessionMonth?: string
    consentGrantedAt: number
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

export function sessionKeyId(teamId: number, sessionId: string): TableKey {
    return { pk: `team:${teamId}:shard:${sessionShard(sessionId)}`, sk: `session:${sessionId}` }
}

export function imageKeyId(teamId: number, consentGrantedAt: number, sessionMonth: string): TableKey {
    return { pk: `team:${teamId}`, sk: `image:${consentGrantedAt}:${sessionMonth}` }
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

export function monthBlockId(month: string): TableKey {
    return { pk: `month:${month}`, sk: 'deleted' }
}

export function monthKeyIndexId(identity: MlKeyIdentity, key: TableKey): TableKey {
    const id = tableKeyString(key)
    return { pk: `month:${keySessionMonth(identity)}:shard:${sessionShard(id)}`, sk: `key:${id}` }
}

export function consentKeyId(organizationId: string): TableKey {
    return { pk: `organization:${organizationId}`, sk: 'consent' }
}

export function teamBlockId(teamId: number): TableKey {
    return { pk: `team:${teamId}`, sk: 'deleted' }
}

export function distinctBlockId(teamId: number, distinctId: string): TableKey {
    return { pk: `team:${teamId}`, sk: `distinct:${identityDigest(distinctId)}` }
}

export function associationIds(identity: MlSessionIdentity): { forward: TableKey; reverse: TableKey } {
    const digest = identityDigest(identity.distinctId)
    return {
        forward: {
            pk: `team:${identity.teamId}:distinct:${digest}:shard:${sessionShard(identity.sessionId)}`,
            sk: `session:${identity.sessionId}`,
        },
        reverse: { pk: `team:${identity.teamId}:session:${identity.sessionId}`, sk: `distinct:${digest}` },
    }
}

export function tableKeyString(key: TableKey): string {
    return JSON.stringify([key.pk, key.sk])
}

export function wrappingContext(identity: MlKeyIdentity): Record<string, string> {
    return {
        purpose: identity.sessionId ? 'ai-research-session' : 'ai-research-image',
        team_id: String(identity.teamId),
        organization_id: identity.organizationId,
        consent_granted_at: String(identity.consentGrantedAt),
        ...(identity.sessionId ? { session_id: identity.sessionId } : {}),
        ...(identity.sessionMonth ? { session_month: identity.sessionMonth } : {}),
    }
}
