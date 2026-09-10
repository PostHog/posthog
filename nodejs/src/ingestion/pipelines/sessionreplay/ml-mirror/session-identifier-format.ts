export const RAW_SESSION_IDENTIFIERS_START_MS = Date.parse('2026-09-11T11:00:00Z')

export function sessionStartTimestampFromUuidV7(sessionId: string): number | null {
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(sessionId)) {
        return null
    }
    const timestamp = Number.parseInt(sessionId.slice(0, 8) + sessionId.slice(9, 13), 16)
    return timestamp > 0 ? timestamp : null
}

export function usesRawSessionIdentifiers(sessionId: string): boolean {
    const startedAt = sessionStartTimestampFromUuidV7(sessionId)
    return startedAt !== null && startedAt >= RAW_SESSION_IDENTIFIERS_START_MS
}
