export const RAW_SESSION_IDENTIFIERS_START_MS = Date.parse('2026-09-15T12:00:00Z')
/** 18:00 Europe/London on 2026-09-21, the first session start that lands in the v3 dataset. */
export const V3_DATASET_START_MS = Date.parse('2026-09-21T17:00:00Z')

export function sessionStartTimestampFromUuidV7(sessionId: string): number | null {
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(sessionId)) {
        return null
    }
    const timestamp = Number.parseInt(sessionId.slice(0, 8) + sessionId.slice(9, 13), 16)
    return timestamp > 0 ? timestamp : null
}

export function usesRawSessionIdentifiers(sessionId: string): boolean {
    const startedAt = sessionStartTimestampFromUuidV7(sessionId)
    return startedAt !== null && startedAt >= RAW_SESSION_IDENTIFIERS_START_MS && startedAt < Date.UTC(10000, 0, 1)
}

export function usesV3Dataset(sessionId: string): boolean {
    const startedAt = sessionStartTimestampFromUuidV7(sessionId)
    return startedAt !== null && startedAt >= V3_DATASET_START_MS && startedAt < Date.UTC(10000, 0, 1)
}

/** The dataset version a session's image references carry, so an image lane stores them next to the session. */
export function mlDatasetVersion(sessionId: string): 2 | 3 {
    return usesV3Dataset(sessionId) ? 3 : 2
}

export const ML_SESSION_MAX_AGE_DAYS = 14
export const ML_SESSION_MAX_FUTURE_DAYS = 1
const DAY_MS = 24 * 60 * 60 * 1000

export type MlSessionIdDropReason = 'session_id_not_uuid_v7' | 'session_id_too_old' | 'session_id_in_future'

/** ML_SESSION_MAX_AGE_DAYS equals MONTH_DELETE_GRACE_DAYS in products/ai_training/backend/privacy/store.py, so a month opens for deletion only once no session that started in it can still arrive. */
export function mlSessionIdDropReason(sessionId: string, nowMs: number): MlSessionIdDropReason | null {
    const startedAt = sessionStartTimestampFromUuidV7(sessionId)
    if (startedAt === null || startedAt >= Date.UTC(10000, 0, 1)) {
        return 'session_id_not_uuid_v7'
    }
    if (startedAt < nowMs - ML_SESSION_MAX_AGE_DAYS * DAY_MS) {
        return 'session_id_too_old'
    }
    if (startedAt > nowMs + ML_SESSION_MAX_FUTURE_DAYS * DAY_MS) {
        return 'session_id_in_future'
    }
    return null
}

export function sessionStartMonth(sessionId: string): string {
    const timestamp = sessionStartTimestampFromUuidV7(sessionId)
    if (timestamp === null) {
        throw new Error('ML monthly partitions require a UUIDv7 session ID')
    }
    const month = new Date(timestamp).toISOString().slice(0, 7)
    if (!/^[0-9]{4}-(0[1-9]|1[0-2])$/.test(month)) {
        throw new Error('ML session month is out of range')
    }
    return month
}
